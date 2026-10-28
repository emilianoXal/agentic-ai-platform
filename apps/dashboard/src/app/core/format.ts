/** Display time zone for the pilot municipality; storage is always UTC. */
export const DISPLAY_TIME_ZONE = 'America/Mexico_City';

const absoluteFormat = new Intl.DateTimeFormat('en-US', {
  timeZone: DISPLAY_TIME_ZONE,
  month: '2-digit',
  day: '2-digit',
  year: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
});

const clockFormat = new Intl.DateTimeFormat('es-MX', {
  timeZone: DISPLAY_TIME_ZONE,
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

export function formatAbsolute(iso: string): string {
  return absoluteFormat.format(new Date(iso));
}

/** 24 h clock used inside the bot's es-MX messages. */
export function formatClockEs(iso: string): string {
  return clockFormat.format(new Date(iso));
}

export function formatRelative(iso: string, now: number = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (seconds < 45) return 'just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return `${days} d ago`;
}

export function isoMinutesAgo(minutes: number, now: number = Date.now()): string {
  return new Date(now - minutes * 60_000).toISOString();
}
