import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { I18nService, Lang } from '../core/i18n';

/** EN | ES segmented control. English is the default; the choice is remembered per browser. */
@Component({
  selector: 'fy-language-switch',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="switch" role="group" [attr.aria-label]="i18n.t('lang.label')">
      @for (option of options; track option.lang) {
        <button
          type="button"
          [class.on]="i18n.lang() === option.lang"
          [attr.aria-pressed]="i18n.lang() === option.lang"
          [attr.lang]="option.lang"
          [attr.title]="option.name"
          (click)="i18n.set(option.lang)"
        >
          {{ option.short }}
        </button>
      }
    </div>
  `,
  host: { '[class.on-dark]': 'onDark()' },
  styles: `
    .switch {
      display: inline-flex;
      padding: 2px;
      border-radius: var(--radius-pill);
      border: 1px solid var(--line-strong);
      background: var(--surface-raised);
    }
    :host(.on-dark) .switch {
      border-color: rgba(244, 245, 241, 0.35);
      background: transparent;
    }
    button {
      min-width: 36px;
      height: 28px;
      padding: 1px 10px 0;
      border: 0;
      border-radius: var(--radius-pill);
      background: transparent;
      color: inherit;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.02em;
      cursor: pointer;
      transition:
        background-color var(--motion-fast) var(--ease-standard),
        color var(--motion-fast) var(--ease-standard);
    }
    :host(.on-dark) button {
      color: var(--topbar-fg);
    }
    button.on {
      background: var(--amarillo-vial);
      color: var(--on-amarillo);
    }
    :host(.on-dark) button.on {
      color: var(--on-amarillo);
    }
    button:focus-visible {
      outline: 2px solid var(--focus-ring);
      outline-offset: 2px;
    }
  `,
})
export class LanguageSwitch {
  readonly onDark = input(false);
  protected readonly i18n = inject(I18nService);

  protected readonly options: readonly { lang: Lang; short: string; name: string }[] = [
    { lang: 'en', short: 'EN', name: 'English' },
    { lang: 'es', short: 'ES', name: 'Español' },
  ];
}
