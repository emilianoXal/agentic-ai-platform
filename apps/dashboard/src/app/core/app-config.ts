import { InjectionToken } from '@angular/core';

/**
 * Runtime configuration, read from /config.json before the app boots.
 * The main-branch deploy job writes it from the Terraform outputs of
 * modules/portal; local development uses public/config.json.
 */
export interface AppConfig {
  /** "appsync" talks to the real backend; "synthetic" runs fully in the browser. */
  readonly dataSource: 'appsync' | 'synthetic';
  readonly region: string;
  readonly userPoolId?: string;
  readonly userPoolClientId?: string;
  readonly graphqlUrl?: string;
  /** Amazon Location API key (browser key restricted to tiles + reverse geocoding). */
  readonly mapsApiKey?: string;
  /** Map center when the browser does not share the user's location. */
  readonly defaultCenter: { readonly lat: number; readonly lng: number };
  readonly defaultCenterLabel: string;
}

export const APP_CONFIG = new InjectionToken<AppConfig>('APP_CONFIG');

/** Querétaro, Qro. Used only until the browser shares the user's location. */
export const FALLBACK_CONFIG: AppConfig = {
  dataSource: 'synthetic',
  region: 'us-east-1',
  defaultCenter: { lat: 20.5931, lng: -100.3921 },
  defaultCenterLabel: 'Querétaro',
};

export async function loadAppConfig(): Promise<AppConfig> {
  try {
    const response = await fetch('config.json', { cache: 'no-store' });
    if (!response.ok) return FALLBACK_CONFIG;
    const raw = (await response.json()) as Partial<AppConfig>;
    const live =
      raw.dataSource === 'appsync' &&
      !!raw.graphqlUrl &&
      !!raw.userPoolId &&
      !!raw.userPoolClientId;
    return {
      ...FALLBACK_CONFIG,
      ...raw,
      dataSource: live ? 'appsync' : 'synthetic',
      defaultCenter: raw.defaultCenter ?? FALLBACK_CONFIG.defaultCenter,
    };
  } catch {
    return FALLBACK_CONFIG;
  }
}
