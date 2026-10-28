import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { IncidentsGateway } from '../../core/incidents-gateway';
import { APP_CONFIG } from '../../core/app-config';
import { I18nService, TranslatePipe } from '../../core/i18n';
import { UserLocationService } from '../../core/location';
import { SessionService } from '../../core/session';
import { ThemeService } from '../../core/theme';
import { BrandMark } from '../../shared/brand-mark';
import { Icon } from '../../shared/icon';
import { LanguageSwitch } from '../../shared/language-switch';
import { PhoneMirror } from '../demo/phone-mirror';

@Component({
  selector: 'fy-shell',
  imports: [
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    BrandMark,
    Icon,
    LanguageSwitch,
    PhoneMirror,
    TranslatePipe,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './shell.html',
  styleUrl: './shell.css',
})
export class Shell {
  private readonly router = inject(Router);
  private readonly gateway = inject(IncidentsGateway);
  private readonly config = inject(APP_CONFIG);
  protected readonly sessions = inject(SessionService);
  protected readonly theme = inject(ThemeService);
  private readonly i18n = inject(I18nService);

  protected readonly location = inject(UserLocationService);
  protected readonly place = computed(() =>
    this.location.source() === 'device'
      ? this.i18n.t('shell.yourLocation')
      : this.config.defaultCenterLabel,
  );
  protected readonly simulated = this.gateway.simulated;
  protected readonly phoneOpen = signal(false);

  protected readonly scope = computed(() => {
    const session = this.sessions.session();
    if (!session) return '';
    return session.agencyId
      ? this.gateway.agencyName(session.agencyId)
      : this.i18n.t('shell.allAgencies');
  });

  constructor() {
    // Load incidents and open the real-time channel for the signed-in user.
    void this.gateway.start();
  }

  protected async signOut(): Promise<void> {
    this.gateway.stop();
    await this.sessions.signOut();
    void this.router.navigateByUrl('/sign-in');
  }
}
