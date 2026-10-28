import {
  ApplicationConfig,
  inject,
  provideAppInitializer,
  provideBrowserGlobalErrorListeners,
} from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import { Amplify } from 'aws-amplify';
import { routes } from './app.routes';
import { APP_CONFIG, AppConfig } from './core/app-config';
import { AppSyncIncidentsGateway } from './core/appsync-gateway';
import { IncidentsGateway } from './core/incidents-gateway';
import { SessionService } from './core/session';
import { SyntheticIncidentsGateway } from './core/synthetic-gateway';

/** Builds the providers from the runtime config loaded in main.ts. */
export function buildAppConfig(config: AppConfig): ApplicationConfig {
  const live = config.dataSource === 'appsync';
  if (live) {
    Amplify.configure({
      Auth: {
        Cognito: { userPoolId: config.userPoolId!, userPoolClientId: config.userPoolClientId! },
      },
      API: {
        GraphQL: {
          endpoint: config.graphqlUrl!,
          region: config.region,
          defaultAuthMode: 'userPool',
        },
      },
    });
  }

  return {
    providers: [
      provideBrowserGlobalErrorListeners(),
      provideRouter(routes, withComponentInputBinding()),
      { provide: APP_CONFIG, useValue: config },
      live ? AppSyncIncidentsGateway : SyntheticIncidentsGateway,
      {
        provide: IncidentsGateway,
        useExisting: live ? AppSyncIncidentsGateway : SyntheticIncidentsGateway,
      },
      provideAppInitializer(() => inject(SessionService).restore()),
    ],
  };
}
