import { Injectable, InjectionToken, inject, signal } from '@angular/core';
import { followUpMessage, FOLLOW_UP_REPLIES, statusMessage } from './bot-messages';
import { DemoControls, GatewayState, IncidentsGateway } from './incidents-gateway';
import { ReverseGeocoder, UserLocationService } from './location';
import { STATUS } from './labels';
import {
  GatewayEvent,
  GatewayEventKind,
  Incident,
  OutboundMessage,
  StatusChangeInput,
  StatusCode,
  TimelineEntry,
} from './models';
import { AGENCIES, buildNewIncident, buildScenario, DEMO_CITIZEN, nextId } from './scenario';
import { CATEGORY } from './labels';

/** Simulated notifier latency between the status write and the WhatsApp send. */
export const NOTIFY_DELAY_MS = new InjectionToken<number>('NOTIFY_DELAY_MS', {
  factory: () => 900,
});

/**
 * In-memory gateway over the synthetic demo data set (placed around the user).
 * It reproduces the real loop (status write → event → notifier → WhatsApp)
 * so the demo behaves like production, and labels everything as simulated.
 */
@Injectable()
export class SyntheticIncidentsGateway extends IncidentsGateway implements DemoControls {
  readonly simulated = true;

  private readonly notifyDelay = inject(NOTIFY_DELAY_MS);
  private readonly location = inject(UserLocationService);
  private readonly geocoder = inject(ReverseGeocoder);
  private readonly state$ = signal<readonly Incident[]>(buildScenario(this.location.position()));
  private readonly outbox = signal<readonly OutboundMessage[]>([]);
  private readonly event = signal<GatewayEvent | null>(null);
  private readonly status = signal<GatewayState>('idle');
  private nonce = 0;
  private started = false;

  readonly incidents = this.state$.asReadonly();
  readonly agencies = signal(AGENCIES).asReadonly();
  readonly messages = this.outbox.asReadonly();
  readonly lastEvent = this.event.asReadonly();
  readonly state = this.status.asReadonly();
  readonly error = signal<string | null>(null).asReadonly();

  /** Places the demo set around the user's location, then names places when possible. */
  async start(): Promise<void> {
    if (this.started) return;
    this.started = true;
    this.status.set('loading');
    const center = await this.location.locate();
    this.state$.set(buildScenario(center));
    this.status.set('ready');
    void this.nameIncidents();
  }

  stop(): void {
    /* Nothing to unsubscribe from in memory. */
  }

  async loadDetail(): Promise<void> {
    /* Synthetic incidents already carry their detail. */
  }

  async changeStatus(
    incidentId: string,
    to: StatusCode,
    input: StatusChangeInput,
  ): Promise<number> {
    const incident = this.require(incidentId);
    const at = new Date().toISOString();
    const reasonText = input.reason ? `. Reason: ${input.reason}` : '';
    // Newest first: the scheduled follow-up, then the status change, then the comment that explains it.
    const entries: TimelineEntry[] = [];
    if (to === 'resolved') {
      entries.push(
        this.entry('follow_up', '"Is it fixed?" scheduled for neighbors in 24 h', 'bot'),
      );
    }
    entries.push(
      this.entry(
        'status',
        `Marked ${STATUS[to].label.toLowerCase()} by ${input.actor}${reasonText}`,
        'dashboard',
        { status: to, actor: input.actor },
      ),
    );
    if (input.comment?.trim()) {
      entries.push(
        this.entry('comment', input.comment.trim(), 'dashboard', { actor: input.actor }),
      );
    }
    this.update(incidentId, (i) => ({
      ...i,
      status: to,
      updatedAt: at,
      followUpPending: to === 'resolved',
      timeline: [...entries, ...i.timeline],
    }));
    this.emit('status', incidentId);
    return this.notifyNeighbors(incident, to, at, input.reason);
  }

  async addComment(incidentId: string, text: string, actor: string): Promise<void> {
    this.update(incidentId, (i) => ({
      ...i,
      updatedAt: new Date().toISOString(),
      timeline: [this.entry('comment', text, 'dashboard', { actor }), ...i.timeline],
    }));
  }

  async escalate(incidentId: string, actor: string): Promise<void> {
    this.update(incidentId, (i) => ({
      ...i,
      escalated: true,
      updatedAt: new Date().toISOString(),
      timeline: [
        this.entry(
          'escalated',
          `Escalated by ${actor}; e-mail with the full history sent through Amazon SES`,
          'dashboard',
          { actor },
        ),
        ...i.timeline,
      ],
    }));
    this.emit('escalated', incidentId);
  }

  reset(): void {
    this.state$.set(buildScenario(this.location.position()));
    void this.nameIncidents();
    this.outbox.set([]);
    this.event.set(null);
  }

  simulateNeighborJoin(incidentId: string): void {
    const incident = this.require(incidentId);
    const suffix = `••${String(10 + ((incident.reportCount * 13) % 89)).padStart(2, '0')}`;
    this.update(incidentId, (i) => ({
      ...i,
      reportCount: i.reportCount + 1,
      neighbors: [...i.neighbors, suffix],
      updatedAt: new Date().toISOString(),
      timeline: [
        this.entry('joined', `Neighbor ${suffix} joined from WhatsApp`, 'simulated'),
        ...i.timeline,
      ],
    }));
    this.emit('joined', incidentId);
  }

  simulateNewReport(): void {
    const existing = this.state$().find((i) => i.id === 'inc-drain');
    if (existing) {
      this.simulateNeighborJoin(existing.id);
      return;
    }
    const incident = buildNewIncident(this.location.position());
    this.state$.update((list) => [...list, incident]);
    this.emit('created', incident.id);
    void this.nameIncidents([incident.id]);
  }

  sendFollowUpNow(incidentId: string): void {
    const incident = this.require(incidentId);
    if (incident.status !== 'resolved') return;
    const copy = followUpMessage(incident, this.agencyName(incident.agencyId));
    const at = new Date().toISOString();
    this.outbox.update((list) => [
      ...list,
      ...incident.neighbors.map((to) =>
        this.message(incident, to, copy.es, copy.en, 'follow_up', at, { awaitingReply: true }),
      ),
    ]);
    this.update(incidentId, (i) => ({
      ...i,
      followUpPending: false,
      timeline: [
        this.entry(
          'follow_up',
          `"Is it fixed?" sent to ${i.neighbors.length} neighbors (fast-forwarded 24 h for the demo)`,
          'simulated',
        ),
        ...i.timeline,
      ],
    }));
  }

  replyToFollowUp(incidentId: string, fixed: boolean): void {
    const incident = this.require(incidentId);
    const reply = fixed ? FOLLOW_UP_REPLIES.fixed : FOLLOW_UP_REPLIES.notFixed;
    const at = new Date().toISOString();
    this.outbox.update((list) => [
      ...list.map((m) =>
        m.incidentId === incidentId && m.awaitingReply ? { ...m, awaitingReply: false } : m,
      ),
      this.message(incident, DEMO_CITIZEN, reply.es, reply.en, 'reply', at, { fromCitizen: true }),
    ]);
    if (fixed) {
      this.update(incidentId, (i) => ({
        ...i,
        timeline: [
          this.entry('reply', `Neighbor ${DEMO_CITIZEN} confirmed it's fixed`, 'whatsapp'),
          ...i.timeline,
        ],
      }));
      return;
    }
    this.update(incidentId, (i) => ({
      ...i,
      status: 'reopened',
      updatedAt: at,
      timeline: [
        this.entry(
          'reply',
          `Neighbor ${DEMO_CITIZEN} answered "${reply.es}": the incident is reopened`,
          'whatsapp',
          { status: 'reopened' },
        ),
        ...i.timeline,
      ],
    }));
    this.emit('reopened', incidentId);
    void this.notifyNeighbors(this.require(incidentId), 'reopened', at);
  }

  private async notifyNeighbors(
    incident: Incident,
    status: StatusCode,
    at: string,
    reason?: string,
  ): Promise<number> {
    await new Promise((resolve) => setTimeout(resolve, this.notifyDelay));
    const copy = statusMessage(incident, status, this.agencyName(incident.agencyId), at, reason);
    const sentAt = new Date().toISOString();
    const recipients = incident.neighbors;
    this.outbox.update((list) => [
      ...list,
      ...recipients.map((to) => this.message(incident, to, copy.es, copy.en, 'status', sentAt)),
    ]);
    this.update(incident.id, (i) => ({
      ...i,
      timeline: [
        this.entry('notified', `${recipients.length} neighbors notified on WhatsApp`, 'bot'),
        ...i.timeline,
      ],
    }));
    this.emit('notified', incident.id, recipients.length);
    return recipients.length;
  }

  /** Replaces the generic "near you" titles with real street names (Amazon Location). */
  private async nameIncidents(ids?: readonly string[]): Promise<void> {
    if (!this.geocoder.available) return;
    const targets = this.state$().filter((i) => !ids || ids.includes(i.id));
    await Promise.all(
      targets.map(async (incident) => {
        const place = await this.geocoder.lookup(incident.location);
        if (!place?.street) return;
        const label = CATEGORY[incident.category].label;
        this.update(incident.id, (i) => ({
          ...i,
          title: `${label} at ${place.street}`,
          titleEs: `${i.titleEs.split(' que ')[0]} en ${place.street}`,
          neighborhood: place.neighborhood,
        }));
      }),
    );
  }

  private require(incidentId: string): Incident {
    const incident = this.state$().find((i) => i.id === incidentId);
    if (!incident) throw new Error(`Incident not found: ${incidentId}`);
    return incident;
  }

  private update(incidentId: string, change: (incident: Incident) => Incident): void {
    this.state$.update((list) => list.map((i) => (i.id === incidentId ? change(i) : i)));
  }

  private emit(kind: GatewayEventKind, incidentId: string, count?: number): void {
    this.nonce += 1;
    this.event.set({ kind, incidentId, nonce: this.nonce, count });
  }

  private entry(
    kind: TimelineEntry['kind'],
    text: string,
    source: TimelineEntry['source'],
    extra: Partial<TimelineEntry> = {},
  ): TimelineEntry {
    return { id: nextId('tl'), at: new Date().toISOString(), kind, text, source, ...extra };
  }

  private message(
    incident: Incident,
    to: string,
    textEs: string,
    textEn: string,
    kind: OutboundMessage['kind'],
    at: string,
    extra: Partial<OutboundMessage> = {},
  ): OutboundMessage {
    return {
      id: nextId('msg'),
      at,
      to,
      incidentId: incident.id,
      folio: incident.folio,
      textEs,
      textEn,
      kind,
      ...extra,
    };
  }
}
