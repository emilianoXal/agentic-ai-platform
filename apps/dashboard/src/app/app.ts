import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { ThemeService } from './core/theme';
import { ToastHost } from './shared/toast-host';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, ToastHost],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<router-outlet /><fy-toast-host />`,
})
export class App {
  // Instantiated at startup so the saved theme applies before the first view renders.
  protected readonly theme = inject(ThemeService);
}
