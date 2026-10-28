import { ChangeDetectionStrategy, Component, computed, input, inject } from '@angular/core';
import { I18nService } from '../core/i18n';
import { SEVERITY } from '../core/labels';
import { Severity } from '../core/models';

/** Severity as 1–4 filled cells plus the word; Critical paints its fourth cell in danger. */
@Component({
  selector: 'fy-severity',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span class="cells" aria-hidden="true">
      @for (cell of cells; track cell) {
        <i [class.filled]="cell <= rank()" [class.critical]="cell === 4 && rank() === 4"></i>
      }
    </span>
    @if (showLabel()) {
      <span class="label">{{ label() }}</span>
    }
    <span class="visually-hidden">{{ aria() }}</span>
  `,
  styles: `
    :host {
      display: inline-flex;
      align-items: center;
      gap: var(--space-2);
      font-size: 13px;
      color: var(--ink-muted);
    }
    .cells {
      display: inline-flex;
      gap: 3px;
    }
    i {
      width: 8px;
      height: 8px;
      border-radius: var(--radius-cell);
      border: 1.5px solid var(--ink);
    }
    i.filled {
      background: var(--ink);
    }
    i.critical {
      background: var(--danger);
      border-color: var(--danger);
    }
  `,
})
export class SeverityCells {
  readonly severity = input.required<Severity>();
  readonly showLabel = input(false);

  protected readonly cells = [1, 2, 3, 4];
  protected readonly rank = computed(() => SEVERITY[this.severity()].rank);
  private readonly i18n = inject(I18nService);
  protected readonly label = computed(() => this.i18n.t(`severity.${this.severity()}`));
  protected readonly aria = computed(() =>
    this.i18n.t('severity.aria', { severity: this.label() }),
  );
}
