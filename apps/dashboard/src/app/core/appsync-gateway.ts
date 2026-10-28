import { Injectable, signal } from '@angular/core';
import { generateClient } from 'aws-amplify/api';
import { GatewayState, IncidentsGateway, LiveDemoControls } from './incidents-gateway';
import { CATEGORY, SEVERITY, STATUS } from './labels';
import {
  Agency,
  CategoryCode,
  GatewayEvent,
  GatewayEventKind,
  Incident,
  LatLng,
  OutboundMessage,
  Severity,
  StatusChangeInput,
  StatusCode,
  TimelineEntry,
} from './models';

const INCIDENT_FIELDS = `
  id folio category title neighborhood geohash
  location { lat lng }
  status escalated severity reportCount agencyId agencyName agencyCaseId
  photoCount neighbors createdAt updatedAt followUpPending
  timeline { id at kind text source status actor }
`;

const LIST_INCIDENTS = `query ListIncidents($limit: Int, $nextToken: String) {
  listIncidents(limit: $limit, nextToken: $nextToken) { items { ${INCIDENT_FIELDS} } nextToken hasMore count }
}`;
const GET_INCIDENT = `query GetIncident($id: ID!) { getIncident(id: $id) { ${INCIDENT_FIELDS} } }`;
const LIST_AGENCIES = `query ListAgencies { listAgencies { id name } }`;
const UPDATE_STATUS = `mutation UpdateIncidentStatus($id: ID!, $status: String!, $comment: String, $reason: String) {
  updateIncidentStatus(id: $id, status: $status, comment: $comment, reason: $reason) { notified incident { ${INCIDENT_FIELDS} } }
}`;
const ADD_COMMENT = `mutation AddIncidentComment($id: ID!, $text: String!) { addIncidentComment(id: $id, text: $text) { ${INCIDENT_FIELDS} } }`;
const ESCALATE = `mutation EscalateIncident($id: ID!) { escalateIncident(id: $id) { ${INCIDENT_FIELDS} } }`;
const SEED_DEMO = `mutation SeedDemoData($lat: Float!, $lng: Float!) { seedDemoData(lat: $lat, lng: $lng) { count } }`;
const RESET_DEMO = `mutation ResetDemoData { resetDemoData }`;
const ON_CHANGE = `subscription OnIncidentChange { onIncidentChange { id kind updatedAt } }`;

const PAGE_SIZE = 100;
const MAX_PAGES = 20;
/** Safety net if the WebSocket drops silently: refresh the list this often. */
const REFRESH_MS = 60_000;

interface RawIncident extends Omit<
  Incident,
  'category' | 'severity' | 'status' | 'titleEs' | 'timeline' | 'neighbors'
> {
  category: string;
  severity: string;
  status: string;
  neighbors: string[];
  timeline: (Omit<TimelineEntry, 'kind' | 'source' | 'status'> & {
    kind: string;
    source: string;
    status: string | null;
  })[];
}

interface GraphQLResponse<T> {
  data?: T;
  errors?: { message: string }[];
}

/**
 * Live data source: AppSync GraphQL with Cognito user pool auth. Incidents arrive
 * paginated; changes from WhatsApp, the dashboard or other staff arrive through
 * the onIncidentChange subscription (fed by the incidents DynamoDB stream).
 */
@Injectable()
export class AppSyncIncidentsGateway extends IncidentsGateway implements LiveDemoControls {
  readonly simulated = false;

  private readonly client = generateClient();
  private readonly list = signal<readonly Incident[]>([]);
  private readonly agencyList = signal<readonly Agency[]>([]);
  private readonly event = signal<GatewayEvent | null>(null);
  private readonly status = signal<GatewayState>('idle');
  private readonly lastError = signal<string | null>(null);
  private subscription: { unsubscribe(): void } | null = null;
  private refreshTimer: ReturnType<typeof setInterval> | null = null;
  private nonce = 0;
  private starting: Promise<void> | null = null;

  readonly incidents = this.list.asReadonly();
  readonly agencies = this.agencyList.asReadonly();
  readonly messages = signal<readonly OutboundMessage[]>([]).asReadonly();
  readonly lastEvent = this.event.asReadonly();
  readonly state = this.status.asReadonly();
  readonly error = this.lastError.asReadonly();

  start(): Promise<void> {
    this.starting ??= this.doStart().finally(() => {
      if (this.status() === 'error') this.starting = null;
    });
    return this.starting;
  }

  stop(): void {
    this.subscription?.unsubscribe();
    this.subscription = null;
    if (this.refreshTimer) clearInterval(this.refreshTimer);
    this.refreshTimer = null;
    this.starting = null;
    this.list.set([]);
    this.status.set('idle');
  }

  async loadDetail(incidentId: string): Promise<void> {
    const data = await this.run<{ getIncident: RawIncident | null }>(GET_INCIDENT, {
      id: incidentId,
    });
    if (data.getIncident) this.upsert(this.toIncident(data.getIncident));
  }

  async changeStatus(
    incidentId: string,
    to: StatusCode,
    input: StatusChangeInput,
  ): Promise<number> {
    const data = await this.run<{
      updateIncidentStatus: { notified: number; incident: RawIncident };
    }>(UPDATE_STATUS, {
      id: incidentId,
      status: to,
      comment: input.comment || null,
      reason: input.reason || null,
    });
    this.upsert(this.toIncident(data.updateIncidentStatus.incident));
    this.emit(to === 'reopened' ? 'reopened' : 'status', incidentId);
    this.emit('notified', incidentId, data.updateIncidentStatus.notified);
    return data.updateIncidentStatus.notified;
  }

  async addComment(incidentId: string, text: string): Promise<void> {
    const data = await this.run<{ addIncidentComment: RawIncident }>(ADD_COMMENT, {
      id: incidentId,
      text,
    });
    this.upsert(this.toIncident(data.addIncidentComment));
  }

  async escalate(incidentId: string): Promise<void> {
    const data = await this.run<{ escalateIncident: RawIncident }>(ESCALATE, { id: incidentId });
    this.upsert(this.toIncident(data.escalateIncident));
    this.emit('escalated', incidentId);
  }

  async seedDemoAt(point: LatLng): Promise<number> {
    const data = await this.run<{ seedDemoData: { count: number } }>(SEED_DEMO, {
      lat: point.lat,
      lng: point.lng,
    });
    await this.loadAll();
    return data.seedDemoData.count;
  }

  async resetDemo(): Promise<number> {
    const data = await this.run<{ resetDemoData: number }>(RESET_DEMO, {});
    await this.loadAll();
    return data.resetDemoData;
  }

  private async doStart(): Promise<void> {
    this.status.set('loading');
    this.lastError.set(null);
    try {
      const [agencies] = await Promise.all([
        this.run<{ listAgencies: Agency[] }>(LIST_AGENCIES, {}),
        this.loadAll(),
      ]);
      this.agencyList.set(agencies.listAgencies);
      this.subscribe();
      this.refreshTimer ??= setInterval(
        () => void this.loadAll().catch(() => undefined),
        REFRESH_MS,
      );
      this.status.set('ready');
    } catch (err) {
      this.lastError.set(this.message(err));
      this.status.set('error');
    }
  }

  /** Reads every page (limit 100, opaque nextToken) and replaces the list. */
  private async loadAll(): Promise<void> {
    const items: Incident[] = [];
    let nextToken: string | null = null;
    for (let page = 0; page < MAX_PAGES; page++) {
      const data: { listIncidents: { items: RawIncident[]; nextToken: string | null } } =
        await this.run(LIST_INCIDENTS, {
          limit: PAGE_SIZE,
          nextToken,
        });
      items.push(...data.listIncidents.items.map((raw) => this.toIncident(raw)));
      nextToken = data.listIncidents.nextToken;
      if (!nextToken) break;
    }
    // Keep detail already loaded (neighbors, timeline) for incidents that did not change.
    const previous = new Map(this.list().map((i) => [i.id, i]));
    this.list.set(
      items.map((i) => {
        const before = previous.get(i.id);
        return before && before.updatedAt === i.updatedAt && before.timeline.length
          ? { ...i, neighbors: before.neighbors, timeline: before.timeline }
          : i;
      }),
    );
  }

  private subscribe(): void {
    if (this.subscription) return;
    const observable = this.client.graphql({ query: ON_CHANGE }) as unknown as {
      subscribe(handlers: {
        next(value: { data?: { onIncidentChange?: { id: string; kind: string } } }): void;
        error(err: unknown): void;
      }): { unsubscribe(): void };
    };
    this.subscription = observable.subscribe({
      next: ({ data }) => {
        const change = data?.onIncidentChange;
        if (change) void this.applyChange(change.id, change.kind);
      },
      error: () => {
        // The periodic refresh keeps the queue current; retry the socket shortly.
        this.subscription = null;
        setTimeout(() => this.subscribe(), 5000);
      },
    });
  }

  /** Turns a stream notification into the motion events the UI understands. */
  private async applyChange(incidentId: string, kind: string): Promise<void> {
    if (kind === 'removed') {
      this.list.update((list) => list.filter((i) => i.id !== incidentId));
      this.emit('removed', incidentId);
      return;
    }
    const before = this.list().find((i) => i.id === incidentId);
    let data: { getIncident: RawIncident | null };
    try {
      data = await this.run(GET_INCIDENT, { id: incidentId });
    } catch {
      return; // Not visible to this user (another agency) or temporarily unavailable.
    }
    if (!data.getIncident) return;
    const after = this.toIncident(data.getIncident);
    this.upsert(after);
    if (!before) this.emit('created', incidentId);
    else if (after.reportCount > before.reportCount) this.emit('joined', incidentId);
    else if (after.status !== before.status)
      this.emit(after.status === 'reopened' ? 'reopened' : 'status', incidentId);
  }

  private upsert(incident: Incident): void {
    this.list.update((list) =>
      list.some((i) => i.id === incident.id)
        ? list.map((i) => (i.id === incident.id ? incident : i))
        : [...list, incident],
    );
  }

  private emit(kind: GatewayEventKind, incidentId: string, count?: number): void {
    this.nonce += 1;
    this.event.set({ kind, incidentId, nonce: this.nonce, count });
  }

  private async run<T>(query: string, variables: Record<string, unknown>): Promise<T> {
    try {
      const result = (await this.client.graphql({ query, variables })) as GraphQLResponse<T>;
      if (result.errors?.length) throw new Error(result.errors[0].message);
      if (!result.data) throw new Error('The dashboard API returned no data.');
      return result.data;
    } catch (err) {
      throw new Error(this.message(err));
    }
  }

  private message(err: unknown): string {
    const raw =
      (err as { errors?: { message: string }[] })?.errors?.[0]?.message ??
      (err instanceof Error ? err.message : String(err));
    // The API prefixes errors with a code ("forbidden: ..."); show only the sentence.
    return raw.replace(/^[a-z_]+:\s*/, '');
  }

  private toIncident(raw: RawIncident): Incident {
    const category = (raw.category in CATEGORY ? raw.category : 'otro') as CategoryCode;
    const severity = (raw.severity in SEVERITY ? raw.severity : 'medium') as Severity;
    const status = (raw.status in STATUS ? raw.status : 'received') as StatusCode;
    return {
      ...raw,
      category,
      severity,
      status,
      titleEs: raw.title,
      neighbors: raw.neighbors ?? [],
      timeline: (raw.timeline ?? []).map((e) => ({
        ...e,
        kind: e.kind as TimelineEntry['kind'],
        source: e.source as TimelineEntry['source'],
        status: e.status && e.status in STATUS ? (e.status as StatusCode) : null,
      })),
    };
  }
}
