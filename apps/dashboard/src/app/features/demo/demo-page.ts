import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import {
  DemoControls,
  hasDemoControls,
  hasLiveDemoControls,
  IncidentsGateway,
} from '../../core/incidents-gateway';
import { UserLocationService } from '../../core/location';
import { STATUS_ACTION } from '../../core/labels';
import { ToastService } from '../../core/toast';
import { Icon } from '../../shared/icon';
import { IconName } from '../../shared/icons.generated';
import { NeighborCount } from '../../shared/neighbor-count';
import { StatusPill } from '../../shared/status-pill';
import { PhoneMirror } from './phone-mirror';

interface DemoStep {
  readonly id: string;
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
  imports: [Icon, NeighborCount, PhoneMirror, RouterLink, StatusPill],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './demo-page.html',
  styleUrl: './demo-page.css',
})
export class DemoPage {
  private readonly gateway = inject(IncidentsGateway);
  private readonly toasts = inject(ToastService);
  private readonly location = inject(UserLocationService);

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
      title: 'A new report arrives',
      detail:
        'A neighbor nearby sends a photo of a blocked storm drain. Its geohash cell flashes and the marker lands on the map.',
      icon: 'map-pin',
      run: () => this.controls()?.simulateNewReport(),
      enabled: () => true,
    },
    {
      id: 'join',
      syntheticOnly: true,
      title: 'A neighbor joins the water leak',
      detail:
        'Instead of a duplicate ticket, the report joins the incident: the counter ticks up and the leak climbs the queue.',
      icon: 'user-plus',
      run: () => this.controls()?.simulateNeighborJoin(this.leak()?.id ?? ''),
      enabled: () => true,
    },
    {
      id: 'in-progress',
      title: 'The water utility starts work',
      detail:
        'The simulated agency marks the leak in progress. Every joined neighbor gets the update on WhatsApp in under a minute.',
      icon: 'tool',
      run: () => this.change('in_progress'),
      enabled: () => ['sent_to_agency', 'reopened', 'received'].includes(this.leak()?.status ?? ''),
    },
    {
      id: 'resolved',
      title: 'The water utility resolves it',
      detail: 'The agency marks it resolved. The bot schedules "Is it fixed?" for 24 hours later.',
      icon: 'circle-check',
      run: () => this.change('resolved'),
      enabled: () => this.leak()?.status === 'in_progress',
    },
    {
      id: 'follow-up',
      syntheticOnly: true,
      title: 'Ask the neighbors: "Is it fixed?"',
      detail:
        'Fast-forwards the 24 hours. Answer on the phone: "No, sigue igual" reopens the incident and alerts the agency.',
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
      this.toasts.show(`Demo data loaded here · ${count} incidents from 30 synthetic reports`);
    } catch (err) {
      this.toasts.show(
        `Demo data was not loaded. ${err instanceof Error ? err.message : ''}`,
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
      this.toasts.show(`Demo data removed · ${removed} synthetic incidents deleted`);
    } catch (err) {
      this.toasts.show(
        `Demo data was not removed. ${err instanceof Error ? err.message : ''}`,
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
    this.toasts.show('Demo reset · 30 reports in 4 incidents');
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
      this.simulated
        ? `${STATUS_ACTION[to].done} · ${notified} neighbors notified`
        : `${STATUS_ACTION[to].done} · WhatsApp update sent to ${notified} neighbors`,
    );
  }
}
