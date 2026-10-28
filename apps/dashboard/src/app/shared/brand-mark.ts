import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * UrbanBot mark: a 3×3 grid of city blocks with the center block in road-marking
 * yellow and a check. `assemble` plays the one-time sign-in animation.
 */
@Component({
  selector: 'fy-brand-mark',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg viewBox="0 0 96 96" [attr.width]="size()" [attr.height]="size()" aria-hidden="true">
      @for (block of blocks; track block.i) {
        <rect
          class="block"
          [class.center]="block.i === 4"
          [attr.x]="block.x"
          [attr.y]="block.y"
          width="26"
          height="26"
          rx="4"
          [style.animation-delay.ms]="block.delay"
        />
      }
      <path class="check" d="M41.2 48.5 L46.2 53.2 L55.0 43.3" />
    </svg>
  `,
  host: { '[class.assemble]': 'assemble()', '[class.on-dark]': 'onDark()' },
  styles: `
    :host {
      display: inline-flex;
      --block: var(--asfalto);
    }
    :host(.on-dark) {
      --block: #4a5960;
    }
    .block {
      fill: var(--block);
      transform-box: fill-box;
      transform-origin: center;
    }
    .block.center {
      fill: var(--amarillo-vial);
    }
    .check {
      fill: none;
      stroke: #1f282d;
      stroke-width: 3.5;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    :host(.assemble) .block {
      animation: block-in 360ms var(--ease-emphasized) backwards;
    }
    :host(.assemble) .block.center {
      animation:
        block-in 360ms var(--ease-emphasized) backwards,
        light-up 300ms var(--ease-standard) 720ms backwards;
    }
    :host(.assemble) .check {
      stroke-dasharray: 24;
      animation: draw 260ms var(--ease-standard) 980ms backwards;
    }
    @keyframes block-in {
      from {
        opacity: 0;
        transform: scale(0.5);
      }
    }
    @keyframes light-up {
      from {
        fill: var(--block);
      }
    }
    @keyframes draw {
      from {
        stroke-dashoffset: 24;
      }
    }
  `,
})
export class BrandMark {
  readonly size = input(28);
  readonly assemble = input(false);
  readonly onDark = input(false);

  /** Blocks assemble clockwise from the top-left, the center block last. */
  protected readonly blocks = (() => {
    const order = [0, 1, 2, 5, 8, 7, 6, 3, 4];
    return Array.from({ length: 9 }, (_, i) => ({
      i,
      x: 3 + (i % 3) * 32,
      y: 3 + Math.floor(i / 3) * 32,
      delay: order.indexOf(i) * 60,
    }));
  })();
}
