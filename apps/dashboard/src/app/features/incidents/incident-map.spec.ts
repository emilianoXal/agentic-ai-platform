// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { incidentMarkerOptions, markerCenterDriftMeters } from './marker-anchor';

describe('incident map marker anchor', () => {
  const queretaroLat = 20.5931;
  const size = 28;

  it('keeps the dot on the same coordinate when the map zooms', () => {
    const anchor = incidentMarkerOptions(document.createElement('button')).anchor;
    const zoomedOut = markerCenterDriftMeters(size, 12, queretaroLat, anchor);
    const zoomedIn = markerCenterDriftMeters(size, 17, queretaroLat, anchor);
    expect(zoomedOut).toBe(0);
    expect(zoomedIn).toBe(0);
    expect(zoomedOut).toBe(zoomedIn);
  });
});
