import { Injectable, inject, signal } from '@angular/core';
import { APP_CONFIG } from './app-config';
import { LatLng } from './models';

export type LocationSource = 'device' | 'default';

/**
 * Where the dashboard user is. The map opens there; synthetic demo data is
 * placed around it. Falls back to the configured default center (Querétaro)
 * when the browser does not share the position.
 */
@Injectable({ providedIn: 'root' })
export class UserLocationService {
  private readonly config = inject(APP_CONFIG);

  readonly position = signal<LatLng>(this.config.defaultCenter);
  readonly source = signal<LocationSource>('default');

  /** Resolves once with the device position, or the default center after a timeout. */
  locate(timeoutMs = 6000): Promise<LatLng> {
    if (!('geolocation' in navigator)) return Promise.resolve(this.position());
    return new Promise((resolve) => {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const point = { lat: pos.coords.latitude, lng: pos.coords.longitude };
          this.position.set(point);
          this.source.set('device');
          resolve(point);
        },
        () => resolve(this.position()),
        { enableHighAccuracy: false, timeout: timeoutMs, maximumAge: 300_000 },
      );
    });
  }
}

export interface PlaceName {
  readonly street: string | null;
  readonly neighborhood: string | null;
}

/** Reverse geocoding through Amazon Location Places (v2) with the browser API key. */
@Injectable({ providedIn: 'root' })
export class ReverseGeocoder {
  private readonly config = inject(APP_CONFIG);
  private readonly cache = new Map<string, Promise<PlaceName | null>>();

  get available(): boolean {
    return !!this.config.mapsApiKey;
  }

  lookup(point: LatLng): Promise<PlaceName | null> {
    if (!this.available) return Promise.resolve(null);
    const key = `${point.lat.toFixed(4)},${point.lng.toFixed(4)}`;
    const cached = this.cache.get(key);
    if (cached) return cached;
    const request = this.fetchPlace(point);
    this.cache.set(key, request);
    return request;
  }

  private async fetchPlace(point: LatLng): Promise<PlaceName | null> {
    const url = `https://places.geo.${this.config.region}.amazonaws.com/v2/reverse-geocode?key=${encodeURIComponent(this.config.mapsApiKey ?? '')}`;
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          QueryPosition: [point.lng, point.lat],
          Language: 'es',
          MaxResults: 1,
        }),
      });
      if (!response.ok) return null;
      const data = (await response.json()) as {
        ResultItems?: {
          Address?: {
            Street?: string;
            AddressNumber?: string;
            District?: string;
            SubDistrict?: string;
            Locality?: string;
          };
        }[];
      };
      const address = data.ResultItems?.[0]?.Address;
      if (!address) return null;
      const street = [address.Street, address.AddressNumber].filter(Boolean).join(' ') || null;
      return {
        street,
        neighborhood: address.District ?? address.SubDistrict ?? address.Locality ?? null,
      };
    } catch {
      return null;
    }
  }
}
