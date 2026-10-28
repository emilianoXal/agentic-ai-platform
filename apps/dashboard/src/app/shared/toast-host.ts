import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { ToastService } from '../core/toast';
import { TranslatePipe } from '../core/i18n';
import { Icon } from './icon';

@Component({
  selector: 'fy-toast-host',
  imports: [Icon, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="stack" role="status" aria-live="polite">
      @for (toast of toasts.toasts(); track toast.id) {
        <div
          class="toast"
          [class.danger]="toast.tone === 'danger'"
          animate.enter="toast-in"
          animate.leave="toast-out"
        >
          <svg [fyIcon]="toast.tone === 'danger' ? 'alert-triangle' : 'check'" [size]="18"></svg>
          <span>{{ toast.text }}</span>
          <button
            type="button"
            class="close"
            (click)="toasts.dismiss(toast.id)"
            [attr.aria-label]="'toast.dismiss' | t"
          >
            <svg fyIcon="x" [size]="16"></svg>
          </button>
        </div>
      }
    </div>
  `,
  styles: `
    .stack {
      position: fixed;
      left: 50%;
      bottom: calc(var(--space-6) + env(safe-area-inset-bottom, 0px));
      transform: translateX(-50%);
      display: grid;
      gap: var(--space-2);
      z-index: 50;
      width: max-content;
      max-width: calc(100vw - 32px);
    }
    .toast {
      display: flex;
      align-items: center;
      gap: var(--space-2);
      padding: 10px 8px 9px 14px;
      border-radius: var(--radius-control);
      background: var(--topbar-bg);
      color: var(--topbar-fg);
      box-shadow: var(--shadow-overlay);
      font-weight: 600;
    }
    .toast.danger {
      background: var(--danger);
      color: #ffffff;
    }
    .close {
      border: 0;
      background: transparent;
      color: inherit;
      display: inline-flex;
      padding: 4px;
      border-radius: var(--radius-control);
      cursor: pointer;
      opacity: 0.8;
    }
    .toast-in {
      animation: toast-in var(--motion-base) var(--ease-emphasized);
    }
    .toast-out {
      animation: toast-in var(--motion-fast) var(--ease-standard) reverse forwards;
    }
    @keyframes toast-in {
      from {
        opacity: 0;
        transform: translateY(16px);
      }
    }
  `,
})
export class ToastHost {
  protected readonly toasts = inject(ToastService);
}
