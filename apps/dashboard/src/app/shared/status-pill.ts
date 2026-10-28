import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  effect,
  input,
  viewChild,
} from '@angular/core';
import { STATUS } from '../core/labels';
import { StatusCode } from '../core/models';
import { Icon } from './icon';

/**
 * Status pill: color, icon and word together, never color alone.
 * The background crossfades and the label slides in when the status changes.
 */
@Component({
  selector: 'fy-status-pill',
  imports: [Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span class="content" #content>
      <svg [fyIcon]="meta().icon" [size]="16"></svg>
      <span>{{ meta().label }}</span>
    </span>
  `,
  host: {
    class: 'pill',
    '[style.--pill-fg]': '"var(--st-" + meta().token + ")"',
    '[style.--pill-bg]': '"var(--st-" + meta().token + "-soft)"',
    '[attr.aria-label]': '"Status: " + meta().label',
  },
  styles: `
    :host {
      display: inline-flex;
      align-items: center;
      height: 24px;
      padding: 0 10px 0 8px;
      border-radius: var(--radius-pill);
      background: var(--pill-bg);
      color: var(--pill-fg);
      font-size: 12px;
      line-height: 16px;
      font-weight: 600;
      letter-spacing: 0.01em;
      white-space: nowrap;
      transition:
        background-color 200ms var(--ease-standard),
        color 200ms var(--ease-standard);
    }
    .content {
      display: inline-flex;
      align-items: center;
      gap: var(--space-1);
      padding-top: 1px;
    }
  `,
})
export class StatusPill {
  readonly status = input.required<StatusCode>();
  protected readonly meta = computed(() => STATUS[this.status()]);

  private readonly content = viewChild.required<ElementRef<HTMLElement>>('content');
  private previous: StatusCode | null = null;

  constructor() {
    // The label slides in only when the status actually changes, never on first render.
    effect(() => {
      const status = this.status();
      const changed = this.previous !== null && this.previous !== status;
      this.previous = status;
      if (changed && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
        this.content().nativeElement.animate(
          [
            { opacity: 0, transform: 'translateY(6px)' },
            { opacity: 1, transform: 'translateY(0)' },
          ],
          { duration: 220, easing: 'cubic-bezier(0.3, 0, 0, 1)' },
        );
      }
    });
  }
}
