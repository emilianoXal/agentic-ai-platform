import { Injectable, effect, signal } from '@angular/core';

export type ThemeChoice = 'system' | 'light' | 'dark';
const STORAGE_KEY = 'urbanbot.theme';

/** Light, dark or follow the OS; sets data-theme on <html>, which the tokens read. */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  readonly choice = signal<ThemeChoice>(this.restore());

  constructor() {
    effect(() => {
      const choice = this.choice();
      const root = document.documentElement;
      if (choice === 'system') root.removeAttribute('data-theme');
      else root.setAttribute('data-theme', choice);
      try {
        localStorage.setItem(STORAGE_KEY, choice);
      } catch {
        /* Storage unavailable; the choice lasts for this visit. */
      }
    });
  }

  isDark(): boolean {
    const choice = this.choice();
    if (choice !== 'system') return choice === 'dark';
    return matchMedia('(prefers-color-scheme: dark)').matches;
  }

  toggle(): void {
    this.choice.set(this.isDark() ? 'light' : 'dark');
  }

  private restore(): ThemeChoice {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      return saved === 'light' || saved === 'dark' ? saved : 'system';
    } catch {
      return 'system';
    }
  }
}
