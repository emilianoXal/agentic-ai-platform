import { describe, expect, it } from 'vitest';
import { encodeGeohash, geohashBounds, offsetMeters } from './geo';

describe('geo', () => {
  const queretaro = { lat: 20.5931, lng: -100.3921 };

  it('encodes a known point to its geohash', () => {
    expect(encodeGeohash({ lat: 57.64911, lng: 10.40744 }, 11)).toBe('u4pruydqqvj');
  });

  it('returns a cell that contains the encoded point', () => {
    const [w, s, e, n] = geohashBounds(encodeGeohash(queretaro));
    expect(queretaro.lng).toBeGreaterThanOrEqual(w);
    expect(queretaro.lng).toBeLessThanOrEqual(e);
    expect(queretaro.lat).toBeGreaterThanOrEqual(s);
    expect(queretaro.lat).toBeLessThanOrEqual(n);
  });

  it('moves a point by meters', () => {
    const moved = offsetMeters(queretaro, 1113.2, 0);
    expect(moved.lat - queretaro.lat).toBeCloseTo(0.01, 4);
    expect(moved.lng).toBeCloseTo(queretaro.lng, 6);
  });
});
