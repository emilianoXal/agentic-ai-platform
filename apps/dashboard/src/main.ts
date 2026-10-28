import { bootstrapApplication } from '@angular/platform-browser';
import { App } from './app/app';
import { buildAppConfig } from './app/app.config';
import { loadAppConfig } from './app/core/app-config';

loadAppConfig()
  .then((config) => bootstrapApplication(App, buildAppConfig(config)))
  .catch((err) => console.error(err));
