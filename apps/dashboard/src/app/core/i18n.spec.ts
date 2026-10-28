import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { I18N_DICTIONARIES, I18nService, interpolate } from './i18n';
import { localizeTimeline, localizeTitle } from './localize';
import { TimelineEntry } from './models';

describe('i18n', () => {
  let i18n: I18nService;

  beforeEach(() => {
    localStorage.removeItem('urbanbot.lang');
    TestBed.configureTestingModule({});
    i18n = TestBed.inject(I18nService);
  });

  it('defaults to English', () => {
    expect(i18n.lang()).toBe('en');
    expect(i18n.t('shell.incidents')).toBe('Incidents');
  });

  it('defines every key in both languages', () => {
    const en = Object.keys(I18N_DICTIONARIES.en).sort();
    const es = Object.keys(I18N_DICTIONARIES.es).sort();
    expect(es).toEqual(en);
    expect(Object.values(I18N_DICTIONARIES.es).every((v) => v.trim().length > 0)).toBe(true);
  });

  it('switches language and remembers it', () => {
    i18n.set('es');
    TestBed.tick();
    expect(i18n.t('shell.incidents')).toBe('Incidentes');
    expect(i18n.locale()).toBe('es-MX');
    expect(localStorage.getItem('urbanbot.lang')).toBe('es');
  });

  it('interpolates parameters', () => {
    expect(interpolate('{count} neighbors', { count: 12 })).toBe('12 neighbors');
    expect(interpolate('{missing} stays', {})).toBe('{missing} stays');
  });

  it('localizes incident titles written in English by the backend', () => {
    i18n.set('es');
    expect(localizeTitle('Water leak at Calle Madero 10', i18n)).toBe(
      'Fuga de agua en Calle Madero 10',
    );
    expect(localizeTitle('Street lights out near you', i18n)).toBe(
      'Luminarias apagadas cerca de ti',
    );
    expect(localizeTitle('Pothole near 9ewmq3h', i18n)).toBe('Bache cerca de 9ewmq3h');
    expect(localizeTitle('Something else', i18n)).toBe('Something else');
  });

  it('localizes timeline entries from their kind and fields', () => {
    i18n.set('es');
    const base = { id: '1', at: '2026-10-27T10:00:00Z', source: 'dashboard' } as const;
    const status: TimelineEntry = {
      ...base,
      kind: 'status',
      status: 'in_progress',
      actor: 'Ana',
      text: 'Marked in progress by Ana',
    };
    const notified: TimelineEntry = {
      ...base,
      kind: 'notified',
      text: 'StatusChanged sent to the notifier for 12 neighbors',
    };
    const routed: TimelineEntry = {
      ...base,
      kind: 'routed',
      text: 'Assigned to Organismo de Agua by routing rule; agency email pending',
    };
    const routedMailed: TimelineEntry = {
      ...routed,
      text: 'Assigned to Organismo de Agua by routing rule; agency email sent',
    };
    const supervisor: TimelineEntry = {
      ...base,
      kind: 'status',
      text: 'Email sent to the supervisor',
    };
    const mailedNoName: TimelineEntry = {
      ...base,
      kind: 'status',
      status: 'sent_to_agency',
      text: 'Agency email sent',
    };
    const mailed: TimelineEntry = {
      ...base,
      kind: 'status',
      status: 'sent_to_agency',
      text: 'Agency email sent to Organismo de Agua',
    };
    const comment: TimelineEntry = { ...base, kind: 'comment', text: 'Válvula cambiada' };
    expect(localizeTimeline(status, i18n)).toBe('Marcado en atención por Ana');
    expect(localizeTimeline(notified, i18n)).toBe('12 vecinos avisados por WhatsApp');
    expect(localizeTimeline(routed, i18n)).toBe(
      'Turnado a Organismo de Agua por regla de ruteo; correo a la dependencia pendiente',
    );
    expect(localizeTimeline(routedMailed, i18n)).toBe(
      'Turnado a Organismo de Agua por regla de ruteo; correo a la dependencia enviado',
    );
    expect(localizeTimeline(supervisor, i18n)).toBe('Correo enviado al supervisor');
    expect(localizeTimeline(mailedNoName, i18n)).toBe('Correo enviado a la dependencia');
    expect(localizeTimeline(mailed, i18n)).toBe('Correo enviado a Organismo de Agua');
    expect(localizeTimeline(comment, i18n)).toBe('Válvula cambiada');
  });
});
