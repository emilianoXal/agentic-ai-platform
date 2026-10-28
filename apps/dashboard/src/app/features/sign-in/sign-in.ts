import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { APP_CONFIG } from '../../core/app-config';
import { Session } from '../../core/models';
import { SessionService, SignInResult } from '../../core/session';
import { BrandMark } from '../../shared/brand-mark';
import { Icon } from '../../shared/icon';
import { IconName } from '../../shared/icons.generated';

interface DemoAccount {
  readonly session: Session;
  readonly title: string;
  readonly description: string;
  readonly icon: IconName;
}

type Step = 'credentials' | 'new_password';

@Component({
  selector: 'fy-sign-in',
  imports: [BrandMark, Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './sign-in.html',
  styleUrl: './sign-in.css',
})
export class SignIn {
  private readonly sessions = inject(SessionService);
  private readonly router = inject(Router);
  private readonly config = inject(APP_CONFIG);

  protected readonly live = this.sessions.live;
  protected readonly placeLabel = this.config.defaultCenterLabel;
  protected readonly step = signal<Step>('credentials');
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
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
      title: 'Agency operator',
      description:
        'Organismo de Agua. Works the incidents routed to the agency and updates their status.',
      icon: 'droplet',
    },
    {
      session: { name: 'Municipal supervisor', role: 'official' },
      title: 'Municipal supervisor',
      description: 'All agencies. Catches stale and reopened cases and escalates them.',
      icon: 'building-community',
    },
    {
      session: { name: 'Demo presenter', role: 'admin' },
      title: 'Demo presenter',
      description: 'Supervisor access plus the demo console and the WhatsApp phone mirror.',
      icon: 'device-mobile',
    },
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
      this.error.set('The two passwords do not match. Type the same password in both fields.');
      return;
    }
    await this.attempt(() => this.sessions.setNewPassword(password));
  }

  private async attempt(action: () => Promise<SignInResult>): Promise<void> {
    this.busy.set(true);
    this.error.set(null);
    try {
      const result = await action();
      if (result === 'signed_in') {
        if (!this.sessions.session()) {
          this.error.set(
            'Your account has no dashboard role yet. Ask an administrator to add you to the agency, official or admin group.',
          );
          await this.sessions.signOut();
          return;
        }
        void this.router.navigateByUrl(this.sessions.isPresenter() ? '/demo' : '/incidents');
      } else if (result === 'new_password_required') {
        this.step.set('new_password');
      } else {
        this.error.set(
          'This account needs a sign-in step the dashboard does not support yet. Contact an administrator.',
        );
      }
    } catch (err) {
      this.error.set(this.explain(err));
    } finally {
      this.busy.set(false);
    }
  }

  private explain(err: unknown): string {
    const name = (err as { name?: string })?.name;
    if (name === 'NotAuthorizedException' || name === 'UserNotFoundException')
      return 'The e-mail or password is incorrect. Check them and try again.';
    if (name === 'InvalidPasswordException')
      return 'The new password must have at least 12 characters, with upper and lower case letters, a number and a symbol.';
    if (name === 'UserAlreadyAuthenticatedException')
      return 'You are already signed in. Reload the page.';
    return err instanceof Error
      ? err.message
      : 'Sign-in failed. Check your connection and try again.';
  }
}
