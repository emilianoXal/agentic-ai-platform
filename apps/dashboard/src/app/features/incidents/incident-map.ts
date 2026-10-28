import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  ViewEncapsulation,
  afterNextRender,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import {
  GeoJSONSource,
  GeolocateControl,
  LngLatBounds,
  Map as MapLibreMap,
  Marker,
  NavigationControl,
  StyleSpecification,
  setWorkerUrl,
} from 'maplibre-gl';
import { APP_CONFIG } from '../../core/app-config';
import { I18nService, TranslatePipe } from '../../core/i18n';
import { localizeTitle } from '../../core/localize';
import { geohashBounds } from '../../core/geo';
import { STATUS } from '../../core/labels';
import { UserLocationService } from '../../core/location';
import { GatewayEvent, Incident } from '../../core/models';
import { ThemeService } from '../../core/theme';
import { ICONS } from '../../shared/icons.generated';

const CELL_SOURCE = 'fy-geohash-cell';

// The worker ships as a build asset (angular.json) instead of being bundled.
setWorkerUrl(new URL('maplibre/maplibre-gl-worker.mjs', document.baseURI).href);

/** Marker diameter grows with joined neighbors, so priority is legible from size. */
export function markerSize(reportCount: number): number {
  return Math.round(22 + 6 * Math.sqrt(reportCount));
}

interface MarkerEntry {
  readonly marker: Marker;
  readonly element: HTMLElement;
}

/**
 * Real map: MapLibre GL with Amazon Location's Monochrome style (light or dark),
 * opening at the user's location. Markers: color + glyph = status, size =
 * neighbors joined. Motion comes from state changes only.
 */
@Component({
  selector: 'fy-incident-map',
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  imports: [TranslatePipe],
  templateUrl: './incident-map.html',
  styleUrl: './incident-map.css',
})
export class IncidentMap {
  readonly incidents = input.required<readonly Incident[]>();
  readonly selectedId = input<string | null>(null);
  readonly lastEvent = input<GatewayEvent | null>(null);
  /** Pixels covered by the detail drawer on the right, so fly-to keeps the marker visible. */
  readonly rightInset = input(0);
  readonly select = output<string>();

  private readonly config = inject(APP_CONFIG);
  private readonly location = inject(UserLocationService);
  private readonly theme = inject(ThemeService);
  private readonly i18n = inject(I18nService);
  private readonly container = viewChild.required<ElementRef<HTMLElement>>('map');

  protected readonly usingFallbackTiles = !this.config.mapsApiKey;
  protected readonly ready = signal(false);

  private map: MapLibreMap | null = null;
  private readonly markers = new Map<string, MarkerEntry>();
  private styleDark: boolean | null = null;

  constructor() {
    const destroyRef = inject(DestroyRef);

    afterNextRender(() => {
      this.createMap();
    });

    destroyRef.onDestroy(() => {
      this.map?.remove();
      this.map = null;
    });

    // Keep markers in step with the data (and their labels with the language).
    effect(() => {
      const incidents = this.incidents();
      const selected = this.selectedId();
      this.i18n.lang();
      if (!this.ready()) return;
      untracked(() => this.syncMarkers(incidents, selected));
    });

    // Fly to the selected incident.
    effect(() => {
      const id = this.selectedId();
      if (!this.ready() || !id) return;
      const incident = untracked(this.incidents).find((i) => i.id === id);
      if (incident) untracked(() => this.flyTo(incident));
    });

    // Motion from state changes.
    effect(() => {
      const event = this.lastEvent();
      if (!event || !this.ready()) return;
      untracked(() => this.animate(event));
    });

    // Light or dark basemap with the app theme.
    effect(() => {
      this.theme.choice();
      if (!this.ready()) return;
      untracked(() => this.applyStyle());
    });
  }

  protected locateMe(): void {
    void this.location.locate().then((point) => {
      this.map?.flyTo({ center: [point.lng, point.lat], zoom: 15, duration: this.duration(700) });
    });
  }

  protected fitIncidents(): void {
    const list = this.incidents();
    if (!this.map || list.length === 0) return;
    const bounds = new LngLatBounds();
    list.forEach((i) => bounds.extend([i.location.lng, i.location.lat]));
    this.map.fitBounds(bounds, {
      padding: { top: 80, bottom: 80, left: 80, right: 80 + this.rightInset() },
      maxZoom: 16,
      duration: this.duration(700),
    });
  }

  private createMap(): void {
    const center = this.location.position();
    this.styleDark = this.theme.isDark();
    this.map = new MapLibreMap({
      container: this.container().nativeElement,
      style: this.styleFor(this.styleDark),
      center: [center.lng, center.lat],
      zoom: 14,
      attributionControl: { compact: true },
    });
    this.map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
    this.map.addControl(
      new GeolocateControl({
        positionOptions: { enableHighAccuracy: false },
        trackUserLocation: false,
        showAccuracyCircle: false,
      }),
      'top-right',
    );
    this.map.on('load', () => {
      this.ready.set(true);
      // Open at the user's position once the browser shares it.
      void this.location.locate().then((point) => {
        if (!untracked(this.selectedId)) this.map?.jumpTo({ center: [point.lng, point.lat] });
      });
    });
  }

  private styleFor(dark: boolean): string | StyleSpecification {
    const key = this.config.mapsApiKey;
    if (key) {
      const scheme = dark ? 'Dark' : 'Light';
      return `https://maps.geo.${this.config.region}.amazonaws.com/v2/styles/Monochrome/descriptor?key=${encodeURIComponent(key)}&color-scheme=${scheme}`;
    }
    // Local development without an Amazon Location key: OpenStreetMap raster tiles.
    return {
      version: 8,
      sources: {
        osm: {
          type: 'raster',
          tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
          tileSize: 256,
          maxzoom: 19,
          attribution: '© OpenStreetMap contributors',
        },
      },
      layers: [
        {
          id: 'osm',
          type: 'raster',
          source: 'osm',
          paint: dark
            ? { 'raster-saturation': -1, 'raster-brightness-max': 0.45, 'raster-contrast': 0.1 }
            : { 'raster-saturation': -0.85, 'raster-brightness-min': 0.1 },
        },
      ],
    };
  }

  private applyStyle(): void {
    const dark = this.theme.isDark();
    if (!this.map || dark === this.styleDark) return;
    this.styleDark = dark;
    this.map.setStyle(this.styleFor(dark));
  }

  private syncMarkers(incidents: readonly Incident[], selectedId: string | null): void {
    if (!this.map) return;
    const seen = new Set<string>();
    // Bigger markers first so smaller ones stay on top and clickable.
    [...incidents]
      .sort((a, b) => b.reportCount - a.reportCount)
      .forEach((incident, index) => {
        seen.add(incident.id);
        let entry = this.markers.get(incident.id);
        if (!entry) {
          const element = document.createElement('button');
          element.type = 'button';
          element.className = 'fy-marker';
          element.innerHTML =
            '<span class="fy-marker-dot"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"></svg></span><span class="fy-marker-esc" hidden></span>';
          element.addEventListener('click', (e) => {
            e.stopPropagation();
            this.select.emit(incident.id);
          });
          const marker = new Marker({ element })
            .setLngLat([incident.location.lng, incident.location.lat])
            .addTo(this.map!);
          entry = { marker, element };
          this.markers.set(incident.id, entry);
        }
        this.paintMarker(entry, incident, incident.id === selectedId, index);
      });
    for (const [id, entry] of this.markers) {
      if (!seen.has(id)) {
        entry.marker.remove();
        this.markers.delete(id);
      }
    }
  }

  private paintMarker(
    entry: MarkerEntry,
    incident: Incident,
    selected: boolean,
    order: number,
  ): void {
    const meta = STATUS[incident.status];
    const el = entry.element;
    el.style.setProperty('--marker', `var(--st-${meta.token})`);
    el.style.setProperty('--size', `${markerSize(incident.reportCount)}px`);
    el.style.zIndex = String(selected ? 1000 : order + 1);
    el.classList.toggle('selected', selected);
    const title = localizeTitle(incident.title, this.i18n);
    const statusLabel = this.i18n.t(`status.${incident.status}`);
    el.setAttribute(
      'aria-label',
      this.i18n.t('map.markerAria', { title, status: statusLabel, count: incident.reportCount }),
    );
    el.setAttribute('aria-pressed', String(selected));
    el.title = `${title} · ${statusLabel}`;
    const svg = el.querySelector('svg');
    if (svg && svg.dataset['icon'] !== meta.icon) {
      svg.innerHTML = ICONS[meta.icon] ?? '';
      svg.dataset['icon'] = meta.icon;
    }
    (el.querySelector('.fy-marker-esc') as HTMLElement).hidden = !incident.escalated;
    entry.marker.setLngLat([incident.location.lng, incident.location.lat]);
  }

  private flyTo(incident: Incident): void {
    this.map?.flyTo({
      center: [incident.location.lng, incident.location.lat],
      zoom: Math.max(this.map.getZoom(), 15.5),
      padding: { top: 0, bottom: 0, left: 0, right: this.rightInset() },
      duration: this.duration(650),
      essential: true,
    });
  }

  private animate(event: GatewayEvent): void {
    const entry = this.markers.get(event.incidentId);
    const reduce = this.reducedMotion();
    if ((event.kind === 'notified' || event.kind === 'reopened') && entry && !reduce) {
      const ring = document.createElement('span');
      ring.className = 'fy-ripple';
      entry.element.appendChild(ring);
      setTimeout(() => ring.remove(), 1200);
    }
    if (event.kind === 'joined' && entry && !reduce) {
      entry.element.animate(
        [{ transform: 'scale(1)' }, { transform: 'scale(1.18)' }, { transform: 'scale(1)' }],
        {
          duration: 500,
          easing: 'cubic-bezier(0.3, 0, 0, 1)',
        },
      );
    }
    if (event.kind === 'created') {
      const incident = this.incidents().find((i) => i.id === event.incidentId);
      if (!incident) return;
      this.flashCell(incident.geohash);
      if (entry && !reduce) entry.element.classList.add('dropped');
    }
  }

  /** Outlines the incident's geohash cell once: "a report landed here". */
  private flashCell(geohash: string): void {
    const map = this.map;
    if (!map || !geohash || !map.isStyleLoaded()) return;
    const [w, s, e, n] = geohashBounds(geohash);
    const data = {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          properties: {},
          geometry: {
            type: 'Polygon',
            coordinates: [
              [
                [w, s],
                [e, s],
                [e, n],
                [w, n],
                [w, s],
              ],
            ],
          },
        },
      ],
    } as const;
    const source = map.getSource(CELL_SOURCE) as GeoJSONSource | undefined;
    if (source) source.setData(data);
    else {
      map.addSource(CELL_SOURCE, { type: 'geojson', data });
      map.addLayer({
        id: CELL_SOURCE,
        type: 'line',
        source: CELL_SOURCE,
        paint: {
          'line-color': '#f6c400',
          'line-width': 3,
          'line-opacity': 0,
          'line-opacity-transition': { duration: 300 },
        },
      });
    }
    map.setPaintProperty(CELL_SOURCE, 'line-opacity', 1);
    setTimeout(() => {
      if (this.map?.getLayer(CELL_SOURCE)) {
        this.map.setPaintProperty(CELL_SOURCE, 'line-opacity-transition', { duration: 800 });
        this.map.setPaintProperty(CELL_SOURCE, 'line-opacity', 0);
      }
    }, 900);
  }

  private reducedMotion(): boolean {
    return matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  private duration(ms: number): number {
    return this.reducedMotion() ? 0 : ms;
  }
}
