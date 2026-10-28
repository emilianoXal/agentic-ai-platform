import { Directive, ElementRef, afterEveryRender, inject } from '@angular/core';

/**
 * FLIP reorder: when children marked with data-flip-id change position after a
 * render (a neighbor joined, an incident reopened), they glide from their old
 * place to the new one instead of jumping.
 */
@Directive({ selector: '[fyFlipList]' })
export class FlipList {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private positions = new Map<string, number>();

  constructor() {
    afterEveryRender({
      read: () => this.animateMoves(),
    });
  }

  private animateMoves(): void {
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const next = new Map<string, number>();
    const children =
      this.host.nativeElement.querySelectorAll<HTMLElement>(':scope > [data-flip-id]');
    children.forEach((child) => {
      const id = child.dataset['flipId'];
      if (!id) return;
      const top = child.offsetTop;
      next.set(id, top);
      const before = this.positions.get(id);
      if (!reduce && before !== undefined && before !== top) {
        child.animate(
          [{ transform: `translateY(${before - top}px)` }, { transform: 'translateY(0)' }],
          {
            duration: 320,
            easing: 'cubic-bezier(0.3, 0, 0, 1)',
          },
        );
      }
    });
    this.positions = next;
  }
}
