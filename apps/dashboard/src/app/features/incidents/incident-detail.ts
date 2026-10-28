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
import { I18nService, TranslatePipe } from '../../core/i18n';
import { IncidentsGateway } from '../../core/incidents-gateway';
import { localizeTimeline, localizeTitle, scheduledFollowUpDelay } from '../../core/localize';
import { allowedTransitions, CATEGORY } from '../../core/labels';
import { Incident, StatusCode, TimelineKind, TimelineEntry } from '../../core/models';
import { SessionService } from '../../core/session';
import { Icon } from '../../shared/icon';
import { IconName } from '../../shared/icons.generated';
import { NeighborCount } from '../../shared/neighbor-count';
import { SeverityCells } from '../../shared/severity-cells';
import { StatusPill } from '../../shared/status-pill';

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
  imports: [Icon, NeighborCount, SeverityCells, StatusPill, TranslatePipe],
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
  private readonly i18n = inject(I18nService);

  protected readonly timelineIcon = TIMELINE_ICON;
  protected readonly commentDraft = signal('');
  protected readonly commenting = signal(false);

  protected readonly category = computed(() => CATEGORY[this.incident().category]);
  protected readonly agencyName = computed(
    () =>
      this.incident().agencyName ??
      (this.incident().agencyId
        ? this.gateway.agencyName(this.incident().agencyId)
        : this.i18n.t('detail.notRouted')),
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
    return formatAbsolute(iso, this.i18n.locale());
  }

  /** Only entries that just happened animate in; opening the drawer shows history at rest. */
  protected isFresh(iso: string): boolean {
    return Date.now() - new Date(iso).getTime() < 4000;
  }

  protected relative(iso: string): string {
    return formatRelative(iso, this.i18n);
  }

  protected readonly title = computed(() => localizeTitle(this.incident().title, this.i18n));

  protected readonly followUpDelay = computed(() =>
    scheduledFollowUpDelay(this.incident().timeline),
  );

  protected entryText(entry: TimelineEntry): string {
    return localizeTimeline(entry, this.i18n);
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
