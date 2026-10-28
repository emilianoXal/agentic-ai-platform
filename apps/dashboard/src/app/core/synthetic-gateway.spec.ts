import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { APP_CONFIG, FALLBACK_CONFIG } from './app-config';
import { DEMO_CITIZEN } from './scenario';
import { NOTIFY_DELAY_MS, SyntheticIncidentsGateway } from './synthetic-gateway';

describe('SyntheticIncidentsGateway', () => {
  let gateway: SyntheticIncidentsGateway;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        SyntheticIncidentsGateway,
        { provide: NOTIFY_DELAY_MS, useValue: 0 },
        { provide: APP_CONFIG, useValue: FALLBACK_CONFIG },
      ],
    });
    gateway = TestBed.inject(SyntheticIncidentsGateway);
  });

  const leak = () => gateway.incidents().find((i) => i.id === 'inc-leak')!;

  it('places every incident within 1 km of the default center (Querétaro)', () => {
    for (const incident of gateway.incidents()) {
      expect(Math.abs(incident.location.lat - 20.5931)).toBeLessThan(0.01);
      expect(Math.abs(incident.location.lng + 100.3921)).toBeLessThan(0.01);
      expect(incident.geohash).toHaveLength(7);
    }
  });

  it('starts with 30 reports clustered into 4 incidents (RF-29)', () => {
    const incidents = gateway.incidents();
    expect(incidents).toHaveLength(4);
    expect(incidents.reduce((sum, i) => sum + i.reportCount, 0)).toBe(30);
  });

  it('notifies every joined neighbor when the status changes (RF-19, RF-32)', async () => {
    const notified = await gateway.changeStatus('inc-leak', 'in_progress', {
      actor: 'Water utility',
    });

    expect(notified).toBe(12);
    expect(leak().status).toBe('in_progress');
    expect(gateway.messages()).toHaveLength(12);
    expect(gateway.messages().every((m) => m.textEs.includes('en atención'))).toBe(true);
    expect(leak().timeline[0].text).toBe('12 neighbors notified on WhatsApp');
    expect(gateway.lastEvent()?.kind).toBe('notified');
  });

  it('records the reason and the actor in the audit timeline (RF-15, RF-21)', async () => {
    await gateway.changeStatus('inc-leak', 'not_applicable', {
      actor: 'Water utility',
      reason: 'Private property',
      comment: 'Valve inside a house',
    });
    const kinds = leak()
      .timeline.slice(0, 3)
      .map((e) => e.kind);
    expect(kinds).toEqual(['notified', 'status', 'comment']);
    expect(leak().timeline[1].text).toContain('Reason: Private property');
  });

  it('schedules "Is it fixed?" on resolve and reopens on a negative answer (RF-20)', async () => {
    await gateway.changeStatus('inc-leak', 'in_progress', { actor: 'Water utility' });
    await gateway.changeStatus('inc-leak', 'resolved', { actor: 'Water utility' });
    expect(leak().followUpPending).toBe(true);

    gateway.sendFollowUpNow('inc-leak');
    const question = gateway
      .messages()
      .find((m) => m.to === DEMO_CITIZEN && m.kind === 'follow_up');
    expect(question?.awaitingReply).toBe(true);

    gateway.replyToFollowUp('inc-leak', false);
    expect(leak().status).toBe('reopened');
    expect(gateway.lastEvent()?.kind).toBe('reopened');
    expect(gateway.messages().find((m) => m.id === question?.id)?.awaitingReply).toBe(false);
  });

  it('keeps the incident resolved when the neighbor confirms the fix', async () => {
    await gateway.changeStatus('inc-leak', 'in_progress', { actor: 'Water utility' });
    await gateway.changeStatus('inc-leak', 'resolved', { actor: 'Water utility' });
    gateway.sendFollowUpNow('inc-leak');
    gateway.replyToFollowUp('inc-leak', true);
    expect(leak().status).toBe('resolved');
  });

  it('joins a neighbor instead of creating a duplicate, raising the count', () => {
    gateway.simulateNeighborJoin('inc-leak');
    expect(leak().reportCount).toBe(13);
    expect(leak().neighbors).toHaveLength(13);
    expect(gateway.lastEvent()).toMatchObject({ kind: 'joined', incidentId: 'inc-leak' });
  });

  it('creates the new incident once, then joins further reports to it', () => {
    gateway.simulateNewReport();
    expect(gateway.incidents()).toHaveLength(5);
    expect(gateway.lastEvent()?.kind).toBe('created');
    gateway.simulateNewReport();
    expect(gateway.incidents()).toHaveLength(5);
    expect(gateway.incidents().find((i) => i.id === 'inc-drain')?.reportCount).toBe(2);
  });

  it('marks an escalation on the incident without changing its status (RF-31)', async () => {
    await gateway.escalate('inc-trash', 'Municipal supervisor');
    const trash = gateway.incidents().find((i) => i.id === 'inc-trash')!;
    expect(trash.escalated).toBe(true);
    expect(trash.status).toBe('received');
  });

  it('resets to the initial scenario', async () => {
    await gateway.changeStatus('inc-leak', 'in_progress', { actor: 'Water utility' });
    gateway.reset();
    expect(leak().status).toBe('sent_to_agency');
    expect(gateway.messages()).toHaveLength(0);
  });
});
