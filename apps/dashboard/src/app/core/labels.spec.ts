import { describe, expect, it } from 'vitest';
import { allowedTransitions, compareForQueue, isClosed, priorityOf } from './labels';
import { buildScenario } from './scenario';

describe('priorityOf', () => {
  it('multiplies joined neighbors by severity rank (RF-30)', () => {
    expect(priorityOf({ reportCount: 12, severity: 'high' })).toBe(36);
    expect(priorityOf({ reportCount: 3, severity: 'low' })).toBe(3);
  });
});

describe('compareForQueue', () => {
  it('puts reopened incidents first, then open by priority, closed last', () => {
    const [leak, pothole, light, trash] = buildScenario(
      { lat: 20.5931, lng: -100.3921 },
      Date.UTC(2026, 9, 27, 15),
    );
    const resolvedLeak = { ...leak, status: 'resolved' as const };
    const order = [trash, resolvedLeak, light, pothole].sort(compareForQueue).map((i) => i.id);
    expect(order).toEqual(['inc-pothole', 'inc-light', 'inc-trash', 'inc-leak']);
  });
});

describe('allowedTransitions', () => {
  it('lets an operator start, resolve and resume work', () => {
    expect(allowedTransitions('sent_to_agency', false)).toEqual(['in_progress', 'not_applicable']);
    expect(allowedTransitions('in_progress', false)).toEqual(['resolved']);
    expect(allowedTransitions('reopened', false)).toEqual(['in_progress']);
  });

  it('only lets a supervisor reopen a closed incident', () => {
    expect(allowedTransitions('resolved', false)).toEqual([]);
    expect(allowedTransitions('resolved', true)).toEqual(['reopened']);
  });

  it('treats resolved and not applicable as closed', () => {
    expect(isClosed('resolved')).toBe(true);
    expect(isClosed('not_applicable')).toBe(true);
    expect(isClosed('reopened')).toBe(false);
  });
});
