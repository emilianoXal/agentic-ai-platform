import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { formatAbsolute, formatRelative } from '../../core/format';
import { IncidentsGateway } from '../../core/incidents-gateway';
import { allowedTransitions, CATEGORY, STATUS_ACTION } from '../../core/labels';
import { ChangeSource, Incident, StatusCode, TimelineKind } from '../../core/models';
import { SessionService } from '../../core/session';
import { Icon } from '../../shared/icon';
import { IconName } from '../../shared/icons.generated';
import { NeighborCount } from '../../shared/neighbor-count';
import { SeverityCells } from '../../shared/severity-cells';
import { StatusPill } from '../../shared/status-pill';

const SOURCE_LABEL: Record<ChangeSource, string> = {
  whatsapp: 'WhatsApp',
  dashboard: 'Dashboard',
  routing: 'Routing rule',
  bot: 'Bot',
  simulated: 'Simulated',
};

const TIMELINE_ICON: Record<TimelineKind, IconName> = {
  status: 'circle-check',
  joined: 'user-plus',
  routed: 'route',
  comment: 'message-circle',
  notified: 'send',
  follow_up: 'clock',
  reply: 'message-circle',
  escalated: 'arrow-big-up-lines',
};

/** Detail drawer: what happened, who is affected and the next action, in that order. */
@Component({
  selector: 'fy-incident-detail',
  imports: [Icon, NeighborCount, SeverityCells, StatusPill],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './incident-detail.html',
  styleUrl: './incident-detail.css',
})
export class IncidentDetail {
  readonly incident = input.required<Incident>();
  readonly requestStatus = output<StatusCode>();
  readonly closeDetail = output<void>();

  private readonly gateway = inject(IncidentsGateway);
  private readonly sessions = inject(SessionService);

  protected readonly sourceLabel = SOURCE_LABEL;
  protected readonly timelineIcon = TIMELINE_ICON;
  protected readonly actionLabel = STATUS_ACTION;
  protected readonly commentDraft = signal('');
  protected readonly commenting = signal(false);

  protected readonly category = computed(() => CATEGORY[this.incident().category]);
  protected readonly agencyName = computed(
    () => this.incident().agencyName ?? this.gateway.agencyName(this.incident().agencyId),
  );
  protected readonly isSupervisor = this.sessions.isSupervisor;
  protected readonly transitions = computed(() =>
    allowedTransitions(this.incident().status, this.isSupervisor()),
  );
  protected readonly primary = computed(
    () => this.transitions().find((s) => s !== 'not_applicable') ?? null,
  );
  protected readonly secondary = computed(() =>
    this.transitions().filter((s) => s !== this.primary()),
  );
  protected readonly photos = computed(() =>
    Array.from({ length: this.incident().photoCount }, (_, i) => i),
  );

  protected absolute(iso: string): string {
    return formatAbsolute(iso);
  }

  /** Only entries that just happened animate in; opening the drawer shows history at rest. */
  protected isFresh(iso: string): boolean {
    return Date.now() - new Date(iso).getTime() < 4000;
  }

  protected relative(iso: string): string {
    return formatRelative(iso);
  }

  protected async saveComment(): Promise<void> {
    const text = this.commentDraft().trim();
    if (!text) return;
    await this.gateway.addComment(
      this.incident().id,
      text,
      this.sessions.session()?.name ?? 'Staff',
    );
    this.commentDraft.set('');
    this.commenting.set(false);
  }

  protected async escalate(): Promise<void> {
    await this.gateway.escalate(this.incident().id, this.sessions.session()?.name ?? 'Supervisor');
  }

  protected onDraft(event: Event): void {
    this.commentDraft.set((event.target as HTMLTextAreaElement).value);
  }
}
