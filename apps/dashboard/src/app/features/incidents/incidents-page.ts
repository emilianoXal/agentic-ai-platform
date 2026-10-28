import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  effect,
  inject,
  input,
  signal,
  untracked,
} from '@angular/core';
import { Router } from '@angular/router';
import { formatAbsolute, formatRelative } from '../../core/format';
import { I18nService, TranslatePipe } from '../../core/i18n';
import { IncidentsGateway } from '../../core/incidents-gateway';
import { localizeTitle } from '../../core/localize';
import { CATEGORY, compareForQueue, isClosed } from '../../core/labels';
import { CategoryCode, Incident, StatusCode } from '../../core/models';
import { SessionService } from '../../core/session';
import { ToastService } from '../../core/toast';
import { FlipList } from '../../shared/flip-list';
import { Icon } from '../../shared/icon';
import { NeighborCount } from '../../shared/neighbor-count';
import { SeverityCells } from '../../shared/severity-cells';
import { StatusPill } from '../../shared/status-pill';
import { IncidentMap } from './incident-map';
import { IncidentDetail } from './incident-detail';
import { StatusChangeRequest, StatusDialog } from './status-dialog';

type StatusFilter = 'open' | 'all' | 'closed';

/** Incidents: priority queue, city map and detail drawer with shared selection. */
@Component({
  selector: 'fy-incidents-page',
  imports: [
    IncidentMap,
    FlipList,
    Icon,
    IncidentDetail,
    NeighborCount,
    SeverityCells,
    StatusDialog,
    StatusPill,
    TranslatePipe,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './incidents-page.html',
  styleUrl: './incidents-page.css',
})
export class IncidentsPage {
  /** Bound from the route /incidents/:id. */
  readonly id = input<string | undefined>(undefined);

  private readonly gateway = inject(IncidentsGateway);
  private readonly sessions = inject(SessionService);
  private readonly toasts = inject(ToastService);
  private readonly router = inject(Router);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  protected readonly i18n = inject(I18nService);

  protected readonly statusFilter = signal<StatusFilter>('open');
  protected readonly categoryFilter = signal<CategoryCode | null>(null);
  protected readonly agencyFilter = signal<string | null>(null);
  protected readonly dialogTarget = signal<StatusCode | null>(null);

  protected readonly categories = CATEGORY;
  protected readonly agencies = this.gateway.agencies;
  protected readonly loadState = this.gateway.state;
  protected readonly loadError = this.gateway.error;
  protected readonly simulated = this.gateway.simulated;
  protected readonly lastEvent = this.gateway.lastEvent;
  protected readonly isSupervisor = this.sessions.isSupervisor;

  /** Agency operators only ever see their own agency (RNF: least privilege in the UI too). */
  protected readonly scoped = computed(() => {
    const agencyId = this.sessions.session()?.agencyId ?? this.agencyFilter();
    const all = this.gateway.incidents();
    return agencyId ? all.filter((i) => i.agencyId === agencyId) : all;
  });

  protected readonly queue = computed(() => {
    const status = this.statusFilter();
    const category = this.categoryFilter();
    return this.scoped()
      .filter((i) =>
        status === 'all' ? true : status === 'open' ? !isClosed(i.status) : isClosed(i.status),
      )
      .filter((i) => (category ? i.category === category : true))
      .sort(compareForQueue);
  });

  protected readonly summary = computed(() => {
    const list = this.scoped();
    const today = new Date().toDateString();
    return {
      open: list.filter((i) => !isClosed(i.status)).length,
      inProgress: list.filter((i) => i.status === 'in_progress').length,
      resolvedToday: list.filter(
        (i) => i.status === 'resolved' && new Date(i.updatedAt).toDateString() === today,
      ).length,
      neighbors: list.filter((i) => !isClosed(i.status)).reduce((sum, i) => sum + i.reportCount, 0),
    };
  });

  protected readonly presentCategories = computed(() => {
    const codes = new Set(this.scoped().map((i) => i.category));
    return (Object.keys(CATEGORY) as CategoryCode[]).filter((c) => codes.has(c));
  });

  protected readonly selected = computed<Incident | null>(() => {
    const id = this.id();
    return (id && this.gateway.incidents().find((i) => i.id === id)) || null;
  });

  constructor() {
    // Neighbors and the audit timeline load on demand when an incident opens.
    effect(() => {
      const id = this.id();
      if (id) untracked(() => void this.gateway.loadDetail(id).catch(() => undefined));
    });

    // A reopened incident sweeps violet as it moves to the top of the queue.
    effect(() => {
      const event = this.lastEvent();
      if (event?.kind !== 'reopened') return;
      untracked(() =>
        queueMicrotask(() => {
          const row = this.host.nativeElement.querySelector<HTMLElement>(
            `[data-flip-id="${event.incidentId}"]`,
          );
          row?.animate(
            [
              { backgroundSize: '0% 100%' },
              { backgroundSize: '100% 100%', offset: 0.6 },
              { backgroundSize: '100% 100%' },
            ],
            { duration: 1400, easing: 'cubic-bezier(0.2, 0, 0, 1)' },
          );
        }),
      );
    });
  }

  protected open(id: string): void {
    void this.router.navigate(['/incidents', id]);
  }

  protected closeDetail(): void {
    void this.router.navigate(['/incidents']);
  }

  protected async confirmStatus(request: StatusChangeRequest): Promise<void> {
    const incident = this.selected();
    this.dialogTarget.set(null);
    if (!incident) return;
    const actor = this.sessions.session()?.name ?? 'Staff';
    try {
      const notified = await this.gateway.changeStatus(incident.id, request.to, {
        actor,
        comment: request.comment,
        reason: request.reason,
      });
      this.toasts.show(
        this.i18n.t(this.simulated ? 'incidents.toastSim' : 'incidents.toastLive', {
          done: this.i18n.t(`action.${request.to}.done`),
          count: notified,
        }),
      );
    } catch (err) {
      const detail = err instanceof Error ? err.message : '';
      this.toasts.show(
        this.i18n.t('incidents.saveError', {
          detail: detail || this.i18n.t('incidents.saveErrorFallback'),
        }),
        'danger',
        6000,
      );
    }
  }

  protected relative(iso: string): string {
    return formatRelative(iso, this.i18n);
  }

  protected absolute(iso: string): string {
    return formatAbsolute(iso, this.i18n.locale());
  }

  protected title(raw: string): string {
    return localizeTitle(raw, this.i18n);
  }

  protected retry(): void {
    void this.gateway.start();
  }

  protected setAgency(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.agencyFilter.set(value || null);
  }
}
