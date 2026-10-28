// @vitest-environment jsdom
import { getTestBed, TestBed } from '@angular/core/testing';
import { BrowserTestingModule, platformBrowserTesting } from '@angular/platform-browser/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { I18N_DICTIONARIES, I18nService, interpolate } from './i18n';
import { localizeTimeline, localizeTitle, scheduledFollowUpDelay } from './localize';
import { TimelineEntry } from './models';

const bed = getTestBed();
if (!bed.platform) {
  bed.initTestEnvironment(BrowserTestingModule, platformBrowserTesting());
}

describe('i18n', () => {
  let i18n: I18nService;

  beforeEach(() => {
    localStorage.removeItem('urbanbot.lang');
    TestBed.resetTestingModule();
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
    expect(localizeTitle('Pothole near Centro', i18n)).toBe('Bache cerca de Centro');
    expect(localizeTitle('Pothole near Verde', i18n)).toBe('Bache cerca de Verde');
    expect(localizeTitle('Pothole', i18n)).toBe('Bache');
    expect(localizeTitle('Other', i18n)).toBe('Otro');
    expect(localizeTitle('Something else', i18n)).toBe('Something else');
    i18n.set('en');
    expect(localizeTitle('Water leak at Av. Universidad 1500', i18n)).toBe(
      'Water leak at Av. Universidad 1500',
    );
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
    const scheduled: TimelineEntry = {
      ...base,
      kind: 'follow_up',
      text: '"Is it fixed?" scheduled for neighbors in 5 min',
    };
    const day: TimelineEntry = {
      ...scheduled,
      text: '"Is it fixed?" scheduled for neighbors in 1440 min',
    };
    expect(localizeTimeline(scheduled, i18n)).toBe(
      '"¿Ya quedó?" programado para los vecinos en 5 min',
    );
    expect(localizeTimeline(day, i18n)).toBe(
      '"¿Ya quedó?" programado para los vecinos en 24 h',
    );
    i18n.set('en');
    expect(localizeTimeline(scheduled, i18n)).toBe(
      '"Is it fixed?" scheduled for neighbors in 5 min',
    );
  });

  it('reads the follow-up delay from the scheduled history line', () => {
    const scheduled: TimelineEntry = {
      id: 'f1',
      at: '2026-10-28T17:00:00Z',
      kind: 'follow_up',
      text: '"Is it fixed?" scheduled for neighbors in 5 min',
      source: 'dashboard',
    };
    const sent: TimelineEntry = { ...scheduled, id: 'f2', text: '"Is it fixed?" sent to 3 neighbors' };
    expect(scheduledFollowUpDelay([scheduled])).toBe('5 min');
    expect(scheduledFollowUpDelay([sent, scheduled])).toBe('5 min');
    const day: TimelineEntry = {
      ...scheduled,
      id: 'f0',
      at: '2026-10-27T17:00:00Z',
      text: '"Is it fixed?" scheduled for neighbors in 1440 min',
    };
    expect(scheduledFollowUpDelay([day])).toBe('24 h');
    expect(scheduledFollowUpDelay([sent, scheduled, day])).toBe('5 min');
    expect(scheduledFollowUpDelay([])).toBeNull();
    i18n.set('es');
    expect(i18n.t('detail.waitingFollowUp', { delay: '5 min' })).toBe(
      'Esperando que los vecinos respondan "¿Ya quedó?", que se envía en 5 min.',
    );
    i18n.set('en');
    expect(i18n.t('detail.waitingFollowUp', { delay: '5 min' })).toBe(
      'Waiting for neighbors to answer "Is it fixed?", sent in 5 min.',
    );
  });
});
