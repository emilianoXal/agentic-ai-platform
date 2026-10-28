import { I18nService } from './i18n';
import { Incident, StatusCode, TimelineEntry } from './models';

/**
 * Localizes content that arrives as English text from the backend or the
 * synthetic data set (incident titles and timeline entries), using their kind
 * and structured fields. Free text written by staff (comments) is left as is.
 */

/** English title prefixes the backend, the demo seed and the synthetic set use. */
const TITLE_PREFIXES: readonly [string, string][] = [
  ['Blocked storm drain', 'title.drenaje'],
  ['Street lights out', 'title.alumbrado'],
  ['Overflowing bins', 'title.basura'],
  ['Street lighting', 'category.alumbrado'],
  ['Water leak', 'category.agua'],
  ['Fallen tree', 'category.arbol'],
  ['Drainage', 'category.drenaje'],
  ['Pothole', 'category.bacheo'],
  ['Safety', 'category.seguridad'],
  ['Trash', 'category.basura'],
  ['Pests', 'category.plagas'],
  ['Other', 'category.otro'],
  ['Incident', 'category.otro'],
];

export function localizeTitle(title: string, i18n: I18nService): string {
  const match = TITLE_PREFIXES.find(
    ([prefix]) => title === prefix || title.startsWith(prefix + ' '),
  );
  if (!match) return title;
  const [prefix, key] = match;
  const category = i18n.t(key);
  if (title === prefix) return category;
  const rest = title.slice(prefix.length + 1);
  if (rest === 'near you') return i18n.t('title.nearYou', { category });
  if (rest === 'near the demo point') return i18n.t('title.nearDemo', { category });
  if (rest.startsWith('at ')) return i18n.t('title.at', { category, place: rest.slice(3) });
  if (rest.startsWith('near ')) return i18n.t('title.near', { category, place: rest.slice(5) });
  return title;
}

export function localizeIncidentTitle(
  incident: Pick<Incident, 'title'>,
  i18n: I18nService,
): string {
  return localizeTitle(incident.title, i18n);
}

function statusWord(status: StatusCode | null | undefined, i18n: I18nService): string {
  return status ? i18n.t(`status.${status}`).toLowerCase() : '';
}

/** Delay written by the portal (`in 5 min`) or the demo (`in 24 h`), never a fixed 24 h. */
function followUpDelay(text: string): string | null {
  const minutes = /in (\d+) min\b/.exec(text);
  if (minutes) return formatFollowUpDelay(Number(minutes[1]));
  const hours = /in (\d+) h\b/.exec(text);
  if (hours) return formatFollowUpDelay(Number(hours[1]) * 60);
  return null;
}

function formatFollowUpDelay(minutes: number): string {
  if (minutes > 0 && minutes % 60 === 0) return `${minutes / 60} h`;
  return `${minutes} min`;
}

/** Delay of the latest scheduled "Is it fixed?" on the incident's history, if any. */
export function scheduledFollowUpDelay(timeline: readonly TimelineEntry[]): string | null {
  for (const entry of timeline) {
    if (entry.kind !== 'follow_up' || /sent to \d+/.test(entry.text)) continue;
    const delay = followUpDelay(entry.text);
    if (delay) return delay;
  }
  return null;
}

function firstNumber(text: string): number | null {
  const found = /(\d+)/.exec(text);
  return found ? Number(found[1]) : null;
}

export function localizeTimeline(entry: TimelineEntry, i18n: I18nService): string {
  const text = entry.text ?? '';
  switch (entry.kind) {
    case 'status': {
      if (text.startsWith('First report')) return i18n.t('timeline.firstReport');
      if (text === 'Email sent to the supervisor') return i18n.t('timeline.supervisorEmailSent');
      const mailed = /^Agency email sent(?: to (.+))?$/.exec(text);
      if (mailed) {
        return mailed[1]
          ? i18n.t('timeline.agencyEmailSent', { agency: mailed[1] })
          : i18n.t('timeline.agencyEmailSentNoName');
      }
      if (!entry.status) return text;
      const status = statusWord(entry.status, i18n);
      if (!entry.actor) return i18n.t('timeline.statusNoActor', { status });
      const reason = /Reason: (.+)$/.exec(text)?.[1];
      return reason
        ? i18n.t('timeline.statusReason', { status, actor: entry.actor, reason })
        : i18n.t('timeline.status', { status, actor: entry.actor });
    }
    case 'joined': {
      const n = firstNumber(text.replace(/••\d+/, ''));
      return n && n > 1 ? i18n.t('timeline.joinedMany', { n }) : i18n.t('timeline.joined');
    }
    case 'routed': {
      const assigned = /Assigned to (.+?) by routing rule; agency email (sent|pending)/.exec(text);
      if (assigned) {
        const key = assigned[2] === 'sent' ? 'timeline.routedMailed' : 'timeline.routed';
        return i18n.t(key, { agency: assigned[1] });
      }
      const agency = /Sent to (.+?) by routing rule/.exec(text)?.[1];
      return agency ? i18n.t('timeline.routed', { agency }) : text;
    }
    case 'escalated':
      return i18n.t('timeline.escalated');
    case 'notified': {
      const n = firstNumber(text);
      return n !== null ? i18n.t('timeline.notified', { n }) : text;
    }
    case 'follow_up': {
      const sent = /sent to (\d+)/.exec(text);
      if (sent) return i18n.t('timeline.followUpSent', { n: Number(sent[1]) });
      const delay = followUpDelay(text);
      return delay
        ? i18n.t('timeline.followUpScheduled', { delay })
        : text;
    }
    case 'reply':
      return text.includes('No, sigue igual')
        ? i18n.t('timeline.replyNo')
        : i18n.t('timeline.replyYes');
    case 'comment':
    default:
      return text;
  }
}
