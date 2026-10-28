import { describe, expect, it } from 'vitest';
import { followUpMessage, statusMessage } from './bot-messages';
import { buildScenario } from './scenario';

describe('bot messages', () => {
  const [leak] = buildScenario({ lat: 20.5931, lng: -100.3921 }, Date.UTC(2026, 9, 27, 15));

  it('starts every status message with the status emoji and the case ID', () => {
    const copy = statusMessage(leak, 'in_progress', 'Water utility', '2026-10-27T15:42:00Z');
    expect(copy.es.startsWith('🛠️')).toBe(true);
    expect(copy.es).toContain('FY-2026-000214');
    expect(copy.es).toContain('09:42');
  });

  it('includes the reason when a report does not apply, and offers a human', () => {
    const copy = statusMessage(
      leak,
      'not_applicable',
      'Water utility',
      '2026-10-27T15:42:00Z',
      'Private property',
    );
    expect(copy.es).toContain('Private property');
    expect(copy.es).toContain('asesor');
  });

  it('asks "¿Ya quedó?" in the follow-up', () => {
    expect(followUpMessage(leak, 'Water utility').es.startsWith('¿Ya quedó?')).toBe(true);
  });
});
