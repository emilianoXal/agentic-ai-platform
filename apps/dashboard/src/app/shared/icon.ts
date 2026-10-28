import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  effect,
  inject,
  input,
} from '@angular/core';
import { IconName, ICONS } from './icons.generated';

/**
 * Tabler outline icon (MIT). Icons inherit the color of their text.
 * Markup comes from the generated, build-time icon map, never from user input.
 */
@Component({
  selector: 'svg[fyIcon]',
  template: '',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    'stroke-width': '1.5',
    'stroke-linecap': 'round',
    'stroke-linejoin': 'round',
    'aria-hidden': 'true',
    focusable: 'false',
    '[attr.width]': 'size()',
    '[attr.height]': 'size()',
    style: 'flex: none',
  },
})
export class Icon {
  readonly fyIcon = input.required<IconName>();
  readonly size = input(20);

  private readonly host = inject<ElementRef<SVGSVGElement>>(ElementRef);

  constructor() {
    effect(() => {
      this.host.nativeElement.innerHTML = ICONS[this.fyIcon()] ?? '';
    });
  }
}
