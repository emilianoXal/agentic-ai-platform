import { LatLng } from './models';

const BASE32 = '0123456789bcdefghjkmnpqrstuvwxyz';

/** Moves a point by meters; accurate enough at city scale. */
export function offsetMeters(origin: LatLng, northM: number, eastM: number): LatLng {
  const lat = origin.lat + northM / 111_320;
  const lng = origin.lng + eastM / (111_320 * Math.cos((origin.lat * Math.PI) / 180));
  return { lat, lng };
}

/** Geohash of a point (the bot clusters reports by precision-7 cells, about 150 m). */
export function encodeGeohash(point: LatLng, precision = 7): string {
  const lat: [number, number] = [-90, 90];
  const lng: [number, number] = [-180, 180];
  let hash = '';
  let bits = 0;
  let bit = 0;
  let even = true;
  while (hash.length < precision) {
    const range = even ? lng : lat;
    const value = even ? point.lng : point.lat;
    const mid = (range[0] + range[1]) / 2;
    if (value >= mid) {
      bits = (bits << 1) | 1;
      range[0] = mid;
    } else {
      bits <<= 1;
      range[1] = mid;
    }
    even = !even;
    bit += 1;
    if (bit === 5) {
      hash += BASE32[bits];
      bits = 0;
      bit = 0;
    }
  }
  return hash;
}

/** Bounding box of a geohash cell as [west, south, east, north]. */
export function geohashBounds(geohash: string): [number, number, number, number] {
  const lat: [number, number] = [-90, 90];
  const lng: [number, number] = [-180, 180];
  let even = true;
  for (const char of geohash.toLowerCase()) {
    const index = BASE32.indexOf(char);
    if (index < 0) break;
    for (const mask of [16, 8, 4, 2, 1]) {
      const range = even ? lng : lat;
      const mid = (range[0] + range[1]) / 2;
      if (index & mask) range[0] = mid;
      else range[1] = mid;
      even = !even;
    }
  }
  return [lng[0], lat[0], lng[1], lat[1]];
}
