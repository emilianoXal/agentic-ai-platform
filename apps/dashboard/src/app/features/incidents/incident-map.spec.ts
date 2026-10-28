// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { incidentMarkerOptions } from './marker-anchor';

describe('incident map marker options', () => {
  it('anchors the marker element at its center with no offset and subpixel positioning', () => {
    const element = document.createElement('button');
    const options = incidentMarkerOptions(element);
    expect(options.element).toBe(element);
    expect(options.anchor).toBe('center');
    expect(options.offset).toEqual([0, 0]);
    expect(options.subpixelPositioning).toBe(true);
  });
});
