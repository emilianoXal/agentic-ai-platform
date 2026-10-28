import { Injectable, signal } from '@angular/core';

export interface Toast {
  readonly id: number;
  readonly text: string;
  readonly tone: 'neutral' | 'danger';
}

/** Short confirmations that repeat the action's verb ("Marked in progress · 12 neighbors notified"). */
@Injectable({ providedIn: 'root' })
export class ToastService {
  private readonly items = signal<readonly Toast[]>([]);
  private counter = 0;

  readonly toasts = this.items.asReadonly();

  show(text: string, tone: Toast['tone'] = 'neutral', durationMs = 4000): void {
    this.counter += 1;
    const id = this.counter;
    this.items.update((list) => [...list, { id, text, tone }]);
    setTimeout(() => this.dismiss(id), durationMs);
  }

  dismiss(id: number): void {
    this.items.update((list) => list.filter((t) => t.id !== id));
  }
}
