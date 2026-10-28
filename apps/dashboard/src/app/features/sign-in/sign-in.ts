import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { LanguageSwitch } from '../../shared/language-switch';
import { Router } from '@angular/router';
import { APP_CONFIG } from '../../core/app-config';
import { I18nService, TranslatePipe } from '../../core/i18n';
import { Session } from '../../core/models';
import { SessionService, SignInResult } from '../../core/session';
import { BrandMark } from '../../shared/brand-mark';
import { Icon } from '../../shared/icon';
import { IconName } from '../../shared/icons.generated';

interface DemoAccount {
  readonly session: Session;
  /** i18n keys: signin.role.<role> and signin.role.<role>Desc */
  readonly role: 'agency' | 'official' | 'admin';
  readonly icon: IconName;
}

/** Either a translation key (re-translated when the language changes) or raw text from AWS. */
type SignInError = { readonly key: string } | { readonly text: string };

type Step = 'credentials' | 'new_password';

@Component({
  selector: 'fy-sign-in',
  imports: [BrandMark, Icon, LanguageSwitch, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './sign-in.html',
  styleUrl: './sign-in.css',
})
export class SignIn {
  private readonly sessions = inject(SessionService);
  private readonly router = inject(Router);
  private readonly config = inject(APP_CONFIG);
  private readonly i18n = inject(I18nService);

  protected readonly live = this.sessions.live;
  protected readonly placeLabel = this.config.defaultCenterLabel;
  protected readonly step = signal<Step>('credentials');
  protected readonly busy = signal(false);
  private readonly failure = signal<SignInError | null>(null);
  protected readonly error = computed(() => {
    const failure = this.failure();
    if (!failure) return null;
    return 'key' in failure ? this.i18n.t(failure.key) : failure.text;
  });
  /** Password fields the user chose to reveal (each field has its own show/hide button). */
  protected readonly revealed = signal<ReadonlySet<string>>(new Set());

  protected isRevealed(field: string): boolean {
    return this.revealed().has(field);
  }

  protected toggleReveal(field: string): void {
    this.revealed.update((set) => {
      const next = new Set(set);
      if (next.has(field)) next.delete(field);
      else next.add(field);
      return next;
    });
  }

  protected readonly accounts: readonly DemoAccount[] = [
    {
      session: {
        name: 'Organismo de Agua operator',
        role: 'agency',
        agencyId: 'organismo-de-agua',
      },
      role: 'agency',
      icon: 'droplet',
    },
    {
      session: { name: 'Municipal supervisor', role: 'official' },
      role: 'official',
      icon: 'building-community',
    },
    { session: { name: 'Demo presenter', role: 'admin' }, role: 'admin', icon: 'device-mobile' },
  ];

  protected continueAs(account: DemoAccount): void {
    this.sessions.signInDemo(account.session);
    void this.router.navigateByUrl(account.session.role === 'admin' ? '/demo' : '/incidents');
  }

  protected async submitCredentials(event: Event): Promise<void> {
    event.preventDefault();
    const form = new FormData(event.target as HTMLFormElement);
    await this.attempt(() =>
      this.sessions.signIn(String(form.get('email') ?? ''), String(form.get('password') ?? '')),
    );
  }

  protected async submitNewPassword(event: Event): Promise<void> {
    event.preventDefault();
    const form = new FormData(event.target as HTMLFormElement);
    const password = String(form.get('new-password') ?? '');
    if (password !== String(form.get('confirm-password') ?? '')) {
      this.failure.set({ key: 'signin.err.mismatch' });
      return;
    }
    await this.attempt(() => this.sessions.setNewPassword(password));
  }

  private async attempt(action: () => Promise<SignInResult>): Promise<void> {
    this.busy.set(true);
    this.failure.set(null);
    try {
      const result = await action();
      if (result === 'signed_in') {
        if (!this.sessions.session()) {
          this.failure.set({ key: 'signin.err.noRole' });
          await this.sessions.signOut();
          return;
        }
        void this.router.navigateByUrl(this.sessions.isPresenter() ? '/demo' : '/incidents');
      } else if (result === 'new_password_required') {
        this.step.set('new_password');
      } else {
        this.failure.set({ key: 'signin.err.step' });
      }
    } catch (err) {
      this.failure.set(this.explain(err));
    } finally {
      this.busy.set(false);
    }
  }

  private explain(err: unknown): SignInError {
    const name = (err as { name?: string })?.name;
    if (name === 'NotAuthorizedException' || name === 'UserNotFoundException')
      return { key: 'signin.err.credentials' };
    if (name === 'InvalidPasswordException') return { key: 'signin.err.policy' };
    if (name === 'UserAlreadyAuthenticatedException') return { key: 'signin.err.already' };
    return err instanceof Error && err.message
      ? { text: err.message }
      : { key: 'signin.err.generic' };
  }
}
