import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import {
  DemoControls,
  hasDemoControls,
  hasLiveDemoControls,
  IncidentsGateway,
} from '../../core/incidents-gateway';
import { UserLocationService } from '../../core/location';
import { I18nService, TranslatePipe } from '../../core/i18n';
import { localizeTitle } from '../../core/localize';
import { ToastService } from '../../core/toast';
import { Icon } from '../../shared/icon';
import { IconName } from '../../shared/icons.generated';
import { NeighborCount } from '../../shared/neighbor-count';
import { StatusPill } from '../../shared/status-pill';
import { PhoneMirror } from './phone-mirror';

interface DemoStep {
  readonly id: string;
  /** i18n keys */
  readonly title: string;
  readonly detail: string;
  readonly icon: IconName;
  readonly run: () => Promise<void> | void;
  readonly enabled: () => boolean;
  /** Steps that simulate WhatsApp traffic exist only in the in-browser synthetic mode. */
  readonly syntheticOnly?: boolean;
}

/**
 * Presenter console for the video and the judges: plays the end-to-end story on
 * synthetic data. Each step is a real gateway call; only the agency is simulated.
 */
@Component({
  selector: 'fy-demo-page',
  imports: [Icon, NeighborCount, PhoneMirror, RouterLink, StatusPill, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './demo-page.html',
  styleUrl: './demo-page.css',
})
export class DemoPage {
  private readonly gateway = inject(IncidentsGateway);
  private readonly toasts = inject(ToastService);
  private readonly location = inject(UserLocationService);
  private readonly i18n = inject(I18nService);

  protected readonly done = signal<ReadonlySet<string>>(new Set());
  protected readonly busy = signal(false);
  protected readonly simulated = this.gateway.simulated;
  protected readonly available = hasDemoControls(this.gateway) || hasLiveDemoControls(this.gateway);
  protected readonly locationSource = this.location.source;

  /** The story follows the water leak with the most neighbors. */
  protected readonly leak = computed(() => {
    const leaks = this.gateway.incidents().filter((i) => i.category === 'agua');
    return leaks.sort((a, b) => b.reportCount - a.reportCount)[0] ?? null;
  });
  protected readonly totals = computed(() => {
    const list = this.gateway.incidents();
    return { incidents: list.length, reports: list.reduce((sum, i) => sum + i.reportCount, 0) };
  });

  protected readonly allSteps: readonly DemoStep[] = [
    {
      id: 'new-report',
      syntheticOnly: true,
      title: 'demo.step.newReport',
      detail: 'demo.step.newReportDetail',
      icon: 'map-pin',
      run: () => this.controls()?.simulateNewReport(),
      enabled: () => true,
    },
    {
      id: 'join',
      syntheticOnly: true,
      title: 'demo.step.join',
      detail: 'demo.step.joinDetail',
      icon: 'user-plus',
      run: () => this.controls()?.simulateNeighborJoin(this.leak()?.id ?? ''),
      enabled: () => true,
    },
    {
      id: 'in-progress',
      title: 'demo.step.inProgress',
      detail: 'demo.step.inProgressDetail',
      icon: 'tool',
      run: () => this.change('in_progress'),
      enabled: () => ['sent_to_agency', 'reopened', 'received'].includes(this.leak()?.status ?? ''),
    },
    {
      id: 'resolved',
      title: 'demo.step.resolved',
      detail: 'demo.step.resolvedDetail',
      icon: 'circle-check',
      run: () => this.change('resolved'),
      enabled: () => this.leak()?.status === 'in_progress',
    },
    {
      id: 'follow-up',
      syntheticOnly: true,
      title: 'demo.step.followUp',
      detail: 'demo.step.followUpDetail',
      icon: 'message-circle',
      run: () => this.controls()?.sendFollowUpNow(this.leak()?.id ?? ''),
      enabled: () => this.leak()?.status === 'resolved' && !!this.leak()?.followUpPending,
    },
  ];

  /** Live mode keeps the agency steps; WhatsApp traffic comes from real phones. */
  protected readonly steps = this.allSteps.filter((s) => this.simulated || !s.syntheticOnly);
  protected readonly seeding = signal(false);

  protected async seedHere(): Promise<void> {
    if (!hasLiveDemoControls(this.gateway) || this.seeding()) return;
    this.seeding.set(true);
    try {
      const point = await this.location.locate();
      const count = await this.gateway.seedDemoAt(point);
      this.done.set(new Set());
      this.toasts.show(this.i18n.t('demo.toastLoaded', { count }));
    } catch (err) {
      this.toasts.show(
        this.i18n.t('demo.toastLoadFailed', { detail: err instanceof Error ? err.message : '' }),
        'danger',
        6000,
      );
    } finally {
      this.seeding.set(false);
    }
  }

  protected async resetLive(): Promise<void> {
    if (!hasLiveDemoControls(this.gateway) || this.seeding()) return;
    this.seeding.set(true);
    try {
      const removed = await this.gateway.resetDemo();
      this.done.set(new Set());
      this.toasts.show(this.i18n.t('demo.toastRemoved', { count: removed }));
    } catch (err) {
      this.toasts.show(
        this.i18n.t('demo.toastRemoveFailed', { detail: err instanceof Error ? err.message : '' }),
        'danger',
        6000,
      );
    } finally {
      this.seeding.set(false);
    }
  }

  /** Only the next runnable step gets the yellow primary style: one primary action per view. */
  protected readonly nextStepId = computed(() => {
    const done = this.done();
    this.leak();
    const lastDone = this.steps.reduce((last, s, index) => (done.has(s.id) ? index : last), -1);
    const after = this.steps.slice(lastDone + 1).find((s) => s.enabled());
    return (after ?? this.steps.find((s) => !done.has(s.id) && s.enabled()))?.id ?? null;
  });

  protected title(raw: string): string {
    return localizeTitle(raw, this.i18n);
  }

  protected async runStep(step: DemoStep): Promise<void> {
    if (this.busy() || !step.enabled()) return;
    this.busy.set(true);
    try {
      await step.run();
      this.done.update((set) => new Set(set).add(step.id));
    } finally {
      this.busy.set(false);
    }
  }

  protected reset(): void {
    if (!this.simulated) {
      void this.resetLive();
      return;
    }
    this.controls()?.reset();
    this.done.set(new Set());
    this.toasts.show(this.i18n.t('demo.toastReset'));
  }

  private controls(): DemoControls | null {
    return hasDemoControls(this.gateway) ? this.gateway : null;
  }

  private async change(to: 'in_progress' | 'resolved'): Promise<void> {
    const id = this.leak()?.id;
    if (!id) return;
    const notified = await this.gateway.changeStatus(id, to, {
      actor: 'Organismo de Agua (simulated)',
    });
    this.toasts.show(
      this.i18n.t(this.simulated ? 'incidents.toastSim' : 'incidents.toastLive', {
        done: this.i18n.t(`action.${to}.done`),
        count: notified,
      }),
    );
  }
}
