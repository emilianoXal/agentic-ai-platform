import { Injectable, computed, inject, signal } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { confirmSignIn, fetchAuthSession, signIn, signOut } from 'aws-amplify/auth';
import { APP_CONFIG } from './app-config';
import { Role, Session } from './models';

const DEMO_STORAGE_KEY = 'urbanbot.session';

export type SignInResult = 'signed_in' | 'new_password_required' | 'unsupported_step';

/**
 * Staff session. Live: Amazon Cognito; the role comes from the user's group
 * (agency, official, admin) and the agency scope from custom:agency_id.
 * AppSync enforces the same rules server side; this only shapes the UI.
 * Synthetic mode keeps the demo accounts for local work without a backend.
 */
@Injectable({ providedIn: 'root' })
export class SessionService {
  private readonly config = inject(APP_CONFIG);
  private readonly current = signal<Session | null>(null);

  readonly live = this.config.dataSource === 'appsync';
  readonly session = this.current.asReadonly();
  readonly isSupervisor = computed(() => {
    const role = this.current()?.role;
    return role === 'official' || role === 'admin';
  });
  readonly isPresenter = computed(() => this.current()?.role === 'admin');

  /** Restores the session before the first route resolves. */
  async restore(): Promise<void> {
    if (!this.live) {
      this.current.set(this.readDemo());
      return;
    }
    this.current.set(await this.fromCognito());
  }

  async signIn(email: string, password: string): Promise<SignInResult> {
    const result = await signIn({ username: email.trim(), password });
    return this.afterStep(result.isSignedIn, result.nextStep.signInStep);
  }

  async setNewPassword(password: string): Promise<SignInResult> {
    const result = await confirmSignIn({ challengeResponse: password });
    return this.afterStep(result.isSignedIn, result.nextStep.signInStep);
  }

  signInDemo(session: Session): void {
    this.current.set(session);
    try {
      sessionStorage.setItem(DEMO_STORAGE_KEY, JSON.stringify(session));
    } catch {
      /* Storage can be unavailable (private mode); the session still lives in memory. */
    }
  }

  async signOut(): Promise<void> {
    this.current.set(null);
    if (this.live) {
      await signOut().catch(() => undefined);
      return;
    }
    try {
      sessionStorage.removeItem(DEMO_STORAGE_KEY);
    } catch {
      /* Nothing to clean up. */
    }
  }

  hasRole(...roles: Role[]): boolean {
    const role = this.current()?.role;
    return role !== undefined && roles.includes(role);
  }

  private async afterStep(isSignedIn: boolean, step: string): Promise<SignInResult> {
    if (isSignedIn || step === 'DONE') {
      this.current.set(await this.fromCognito());
      return 'signed_in';
    }
    if (step === 'CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED') return 'new_password_required';
    return 'unsupported_step';
  }

  private async fromCognito(): Promise<Session | null> {
    try {
      const { tokens } = await fetchAuthSession();
      const claims = tokens?.idToken?.payload;
      if (!claims) return null;
      const groups = (claims['cognito:groups'] as string[] | undefined) ?? [];
      const role: Role | null = groups.includes('admin')
        ? 'admin'
        : groups.includes('official')
          ? 'official'
          : groups.includes('agency')
            ? 'agency'
            : null;
      if (!role) return null;
      const email = (claims['email'] as string | undefined) ?? undefined;
      return {
        name: (claims['name'] as string | undefined) ?? email ?? 'Staff',
        email,
        role,
        agencyId:
          role === 'agency'
            ? ((claims['custom:agency_id'] as string | undefined) ?? undefined)
            : undefined,
      };
    } catch {
      return null;
    }
  }

  private readDemo(): Session | null {
    try {
      const raw = sessionStorage.getItem(DEMO_STORAGE_KEY);
      return raw ? (JSON.parse(raw) as Session) : null;
    } catch {
      return null;
    }
  }
}

export const signedInGuard: CanActivateFn = () => {
  const session = inject(SessionService);
  return session.session() ? true : inject(Router).createUrlTree(['/sign-in']);
};

export function roleGuard(...roles: Role[]): CanActivateFn {
  return () => {
    const session = inject(SessionService);
    return session.hasRole(...roles) ? true : inject(Router).createUrlTree(['/incidents']);
  };
}
