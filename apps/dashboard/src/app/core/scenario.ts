import { isoMinutesAgo } from './format';
import { encodeGeohash, offsetMeters } from './geo';
import { Agency, Incident, LatLng, TimelineEntry } from './models';

/**
 * Synthetic demo data set: 30 citizen reports clustered into 4 incidents
 * (RF-29 acceptance test), placed around whoever uses the dashboard (their
 * browser location, or the configured default center). Every agency here is
 * simulated and labeled as such in the UI (RB-08). Places start generic and are
 * renamed with real street names when reverse geocoding is available.
 */

/** The demo citizen whose WhatsApp the phone mirror shows. */
export const DEMO_CITIZEN = '••42';

export const AGENCIES: readonly Agency[] = [
  { id: 'organismo-de-agua', name: 'Organismo de Agua' },
  { id: 'obras-publicas', name: 'Obras Publicas' },
  { id: 'servicios-publicos', name: 'Servicios Publicos' },
  { id: 'limpia-publica', name: 'Limpia Publica' },
];

interface Placement {
  readonly location: LatLng;
  readonly geohash: string;
}

function place(center: LatLng, northM: number, eastM: number): Placement {
  const location = offsetMeters(center, northM, eastM);
  return { location, geohash: encodeGeohash(location) };
}

let sequence = 0;
export function nextId(prefix: string): string {
  sequence += 1;
  return `${prefix}-${Date.now().toString(36)}-${sequence}`;
}

function neighbors(seed: number, count: number, first?: string): string[] {
  const list: string[] = first ? [first] : [];
  let n = seed;
  while (list.length < count) {
    n = (n * 37 + 11) % 97;
    const suffix = `••${String(n).padStart(2, '0')}`;
    if (!list.includes(suffix)) list.push(suffix);
  }
  return list;
}

function entry(
  minutesAgo: number,
  kind: TimelineEntry['kind'],
  text: string,
  source: TimelineEntry['source'],
  now: number,
  extra: Partial<TimelineEntry> = {},
): TimelineEntry {
  return { id: nextId('tl'), at: isoMinutesAgo(minutesAgo, now), kind, text, source, ...extra };
}

/** Builds the initial four incidents relative to the current time. */
export function buildScenario(center: LatLng, now: number = Date.now()): Incident[] {
  const leak = place(center, 120, -80);
  const pothole = place(center, -260, 310);
  const light = place(center, 430, -390);
  const trash = place(center, -160, -460);
  return [
    {
      id: 'inc-leak',
      folio: 'UB-2026-000214',
      category: 'agua',
      title: 'Water leak near you',
      titleEs: 'la fuga de agua que reportaste',
      neighborhood: null,
      ...leak,
      status: 'sent_to_agency',
      escalated: false,
      severity: 'high',
      reportCount: 12,
      agencyId: 'organismo-de-agua',
      photoCount: 3,
      neighbors: neighbors(7, 12, '••42'),
      createdAt: isoMinutesAgo(130, now),
      updatedAt: isoMinutesAgo(78, now),
      followUpPending: false,
      timeline: [
        entry(78, 'status', 'Agency email sent to Organismo de Agua', 'email', now, {
          status: 'sent_to_agency',
        }),
        entry(
          79,
          'routed',
          'Assigned to Organismo de Agua by routing rule; agency email sent',
          'routing',
          now,
        ),
        entry(80, 'joined', '11 neighbors joined between 8:40 and 9:10', 'whatsapp', now),
        entry(130, 'status', 'First report received with 3 photos and a pin', 'whatsapp', now, {
          status: 'received',
        }),
      ],
    },
    {
      id: 'inc-pothole',
      folio: 'UB-2026-000198',
      category: 'bacheo',
      title: 'Pothole near you',
      titleEs: 'el bache que reportaste',
      neighborhood: null,
      ...pothole,
      status: 'reopened',
      escalated: false,
      severity: 'medium',
      reportCount: 9,
      agencyId: 'obras-publicas',
      agencyCaseId: 'OP-77120',
      photoCount: 2,
      neighbors: neighbors(19, 9),
      createdAt: isoMinutesAgo(60 * 30, now),
      updatedAt: isoMinutesAgo(290, now),
      followUpPending: false,
      timeline: [
        entry(
          290,
          'reply',
          'A neighbor answered "No, sigue igual": the pothole came back after the rain',
          'whatsapp',
          now,
          { status: 'reopened' },
        ),
        entry(60 * 6, 'status', 'Marked resolved by Obras Publicas', 'simulated', now, {
          status: 'resolved',
          actor: 'Obras Publicas',
        }),
        entry(60 * 20, 'status', 'Marked in progress by Obras Publicas', 'simulated', now, {
          status: 'in_progress',
          actor: 'Obras Publicas',
        }),
        entry(60 * 29, 'status', 'Agency email sent to Obras Publicas', 'email', now, {
          status: 'sent_to_agency',
        }),
        entry(
          60 * 29 + 1,
          'routed',
          'Assigned to Obras Publicas by routing rule; agency email sent',
          'routing',
          now,
        ),
        entry(60 * 30, 'status', 'First report received', 'whatsapp', now, { status: 'received' }),
      ],
    },
    {
      id: 'inc-light',
      folio: 'UB-2026-000171',
      category: 'alumbrado',
      title: 'Street lights out near you',
      titleEs: 'las luminarias apagadas que reportaste',
      neighborhood: null,
      ...light,
      status: 'in_progress',
      escalated: true,
      severity: 'medium',
      reportCount: 6,
      agencyId: 'servicios-publicos',
      photoCount: 1,
      neighbors: neighbors(31, 6),
      createdAt: isoMinutesAgo(60 * 24 * 4, now),
      updatedAt: isoMinutesAgo(60 * 26, now),
      followUpPending: false,
      timeline: [
        entry(
          60 * 26,
          'escalated',
          'Escalated to the municipal supervisor: open for more than 3 days',
          'bot',
          now,
        ),
        entry(60 * 24 * 3, 'status', 'Marked in progress by Servicios Publicos', 'simulated', now, {
          status: 'in_progress',
          actor: 'Servicios Publicos',
        }),
        entry(60 * 24 * 4 - 30, 'status', 'Agency email sent to Servicios Publicos', 'email', now, {
          status: 'sent_to_agency',
        }),
        entry(
          60 * 24 * 4 - 29,
          'routed',
          'Assigned to Servicios Publicos by routing rule; agency email sent',
          'routing',
          now,
        ),
        entry(60 * 24 * 4, 'status', 'First report received', 'whatsapp', now, {
          status: 'received',
        }),
      ],
    },
    {
      id: 'inc-trash',
      folio: 'UB-2026-000231',
      category: 'basura',
      title: 'Overflowing bins near you',
      titleEs: 'los contenedores llenos que reportaste',
      neighborhood: null,
      ...trash,
      status: 'received',
      escalated: false,
      severity: 'low',
      reportCount: 3,
      agencyId: 'limpia-publica',
      photoCount: 2,
      neighbors: neighbors(53, 3),
      createdAt: isoMinutesAgo(12, now),
      updatedAt: isoMinutesAgo(12, now),
      followUpPending: false,
      timeline: [
        entry(8, 'joined', '2 neighbors joined', 'whatsapp', now),
        entry(12, 'status', 'First report received with 2 photos', 'whatsapp', now, {
          status: 'received',
        }),
      ],
    },
  ];
}

/** The incident created by the "New report arrives" demo step. */
export function buildNewIncident(center: LatLng, now: number = Date.now()): Incident {
  return {
    id: 'inc-drain',
    folio: 'UB-2026-000236',
    category: 'drenaje',
    title: 'Blocked storm drain near you',
    titleEs: 'la coladera tapada que reportaste',
    neighborhood: null,
    ...place(center, 330, 420),
    status: 'received',
    escalated: false,
    severity: 'medium',
    reportCount: 1,
    agencyId: 'obras-publicas',
    photoCount: 1,
    neighbors: neighbors(71, 1),
    createdAt: new Date(now).toISOString(),
    updatedAt: new Date(now).toISOString(),
    followUpPending: false,
    timeline: [
      {
        id: nextId('tl'),
        at: new Date(now).toISOString(),
        kind: 'status',
        text: 'First report received with 1 photo and a voice note',
        source: 'simulated',
        status: 'received',
      },
    ],
  };
}
