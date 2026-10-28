import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  effect,
  inject,
  input,
} from '@angular/core';
import { I18nService } from '../core/i18n';
import { Icon } from './icon';

/** Joined-neighbors counter in road-marking yellow; pulses once when a neighbor joins. */
@Component({
  selector: 'fy-neighbor-count',
  imports: [Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg fyIcon="users" [size]="14"></svg>
    <span class="mono">{{ count() }}</span>
    @if (long()) {
      <span>{{ i18n.t(count() === 1 ? 'neighbors.one' : 'neighbors.many') }}</span>
    }
  `,
  host: {
    '[attr.aria-label]': 'i18n.t("neighbors.count", { count: count() })',
  },
  styles: `
    :host {
      display: inline-flex;
      align-items: center;
      gap: var(--space-1);
      height: 22px;
      padding: 1px 8px 0;
      border-radius: var(--radius-pill);
      background: var(--amarillo-vial);
      color: var(--on-amarillo);
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
    }
    .mono {
      font-family: var(--font-sans);
      font-variant-numeric: tabular-nums;
    }
  `,
})
export class NeighborCount {
  readonly count = input.required<number>();
  readonly long = input(false);

  protected readonly i18n = inject(I18nService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private previous: number | null = null;

  constructor() {
    effect(() => {
      const count = this.count();
      const grew = this.previous !== null && count > this.previous;
      this.previous = count;
      if (grew && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
        this.host.nativeElement.animate(
          [
            { boxShadow: '0 0 0 0 var(--amarillo-vial)', transform: 'scale(1)' },
            {
              boxShadow: '0 0 0 5px color-mix(in srgb, var(--amarillo-vial) 45%, transparent)',
              transform: 'scale(1.12)',
            },
            { boxShadow: '0 0 0 0 transparent', transform: 'scale(1)' },
          ],
          { duration: 600, easing: 'cubic-bezier(0.3, 0, 0, 1)' },
        );
      }
    });
  }
}
