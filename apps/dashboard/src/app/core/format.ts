/** Display time zone for the pilot municipality; storage is always UTC. */
export const DISPLAY_TIME_ZONE = 'America/Mexico_City';

const absoluteFormats = new Map<string, Intl.DateTimeFormat>();

function absoluteFormat(locale: string): Intl.DateTimeFormat {
  let format = absoluteFormats.get(locale);
  if (!format) {
    format = new Intl.DateTimeFormat(locale, {
      timeZone: DISPLAY_TIME_ZONE,
      month: '2-digit',
      day: '2-digit',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
    absoluteFormats.set(locale, format);
  }
  return format;
}

/** Minimal translator contract so this module stays free of Angular. */
export interface Translator {
  t(key: string, params?: Record<string, string | number>): string;
}

const ENGLISH: Translator = {
  t: (key, params) => {
    const n = params?.['n'];
    const table: Record<string, string> = {
      'time.justNow': 'just now',
      'time.minutes': `${n} min ago`,
      'time.hours': `${n} h ago`,
      'time.days': `${n} d ago`,
    };
    return table[key] ?? key;
  },
};

const clockFormat = new Intl.DateTimeFormat('es-MX', {
  timeZone: DISPLAY_TIME_ZONE,
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

/** MM/DD/YYYY h:mm a in English, DD/MM/YYYY HH:mm in Spanish (Mexico City time). */
export function formatAbsolute(iso: string, locale = 'en-US'): string {
  return absoluteFormat(locale).format(new Date(iso));
}

/** 24 h clock used inside the bot's es-MX messages. */
export function formatClockEs(iso: string): string {
  return clockFormat.format(new Date(iso));
}

export function formatRelative(
  iso: string,
  i18n: Translator = ENGLISH,
  now: number = Date.now(),
): string {
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (seconds < 45) return i18n.t('time.justNow');
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return i18n.t('time.minutes', { n: minutes });
  const hours = Math.round(minutes / 60);
  if (hours < 24) return i18n.t('time.hours', { n: hours });
  return i18n.t('time.days', { n: Math.round(hours / 24) });
}

export function isoMinutesAgo(minutes: number, now: number = Date.now()): string {
  return new Date(now - minutes * 60_000).toISOString();
}
