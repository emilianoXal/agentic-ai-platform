import { Routes } from '@angular/router';
import { roleGuard, signedInGuard } from './core/session';

export const routes: Routes = [
  {
    path: 'sign-in',
    title: 'Sign in · UrbanBot',
    loadComponent: () => import('./features/sign-in/sign-in').then((m) => m.SignIn),
  },
  {
    path: '',
    canActivate: [signedInGuard],
    loadComponent: () => import('./features/shell/shell').then((m) => m.Shell),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'incidents' },
      {
        path: 'incidents',
        title: 'Incidents · UrbanBot',
        loadComponent: () =>
          import('./features/incidents/incidents-page').then((m) => m.IncidentsPage),
      },
      {
        path: 'incidents/:id',
        title: 'Incident · UrbanBot',
        loadComponent: () =>
          import('./features/incidents/incidents-page').then((m) => m.IncidentsPage),
      },
      {
        path: 'demo',
        title: 'Demo console · UrbanBot',
        canActivate: [roleGuard('admin')],
        loadComponent: () => import('./features/demo/demo-page').then((m) => m.DemoPage),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
