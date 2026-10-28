import { IconName } from '../shared/icons.generated';
import { CategoryCode, Incident, Severity, StatusCode } from './models';

export interface StatusMeta {
  readonly label: string;
  readonly labelEs: string;
  readonly icon: IconName;
  readonly emoji: string;
  /** CSS custom property suffix: --st-<token> and --st-<token>-soft. */
  readonly token: string;
}

export const STATUS: Record<StatusCode, StatusMeta> = {
  received: {
    label: 'Received',
    labelEs: 'Recibido',
    icon: 'inbox',
    emoji: '📥',
    token: 'recibido',
  },
  sent_to_agency: {
    label: 'Sent to agency',
    labelEs: 'Enviado a dependencia',
    icon: 'send',
    emoji: '📨',
    token: 'enviado',
  },
  sent_by_supervisor: {
    label: 'Sent by supervisor',
    labelEs: 'Enviado por el supervisor',
    icon: 'send',
    emoji: '📨',
    token: 'enviado',
  },
  in_progress: {
    label: 'In progress',
    labelEs: 'En atención',
    icon: 'tool',
    emoji: '🛠️',
    token: 'atencion',
  },
  resolved: {
    label: 'Resolved',
    labelEs: 'Resuelto',
    icon: 'circle-check',
    emoji: '✅',
    token: 'resuelto',
  },
  not_applicable: {
    label: 'Not applicable',
    labelEs: 'No procede',
    icon: 'circle-minus',
    emoji: '⛔',
    token: 'noprocede',
  },
  reopened: {
    label: 'Reopened',
    labelEs: 'Reabierto',
    icon: 'refresh',
    emoji: '🔁',
    token: 'reabierto',
  },
};

export const STATUS_ORDER: readonly StatusCode[] = [
  'received',
  'sent_to_agency',
  'in_progress',
  'resolved',
  'not_applicable',
  'reopened',
];

/** Verb used on buttons and toasts, so the action keeps one name through the flow. */
export const STATUS_ACTION: Record<StatusCode, { button: string; done: string }> = {
  received: { button: 'Mark received', done: 'Marked received' },
  sent_to_agency: { button: 'Send to agency', done: 'Sent to agency' },
  sent_by_supervisor: { button: 'Send to agency', done: 'Sent by supervisor' },
  in_progress: { button: 'Mark in progress', done: 'Marked in progress' },
  resolved: { button: 'Mark resolved', done: 'Marked resolved' },
  not_applicable: { button: 'Mark not applicable', done: 'Marked not applicable' },
  reopened: { button: 'Reopen', done: 'Reopened' },
};

export const SEVERITY: Record<Severity, { label: string; rank: number }> = {
  low: { label: 'Low', rank: 1 },
  medium: { label: 'Medium', rank: 2 },
  high: { label: 'High', rank: 3 },
  critical: { label: 'Critical', rank: 4 },
};

export const CATEGORY: Record<CategoryCode, { label: string; icon: IconName }> = {
  agua: { label: 'Water leak', icon: 'droplet' },
  bacheo: { label: 'Pothole', icon: 'traffic-cone' },
  alumbrado: { label: 'Street lighting', icon: 'bulb' },
  basura: { label: 'Trash', icon: 'trash' },
  drenaje: { label: 'Drainage', icon: 'ripple' },
  arbol: { label: 'Fallen tree', icon: 'tree' },
  plagas: { label: 'Pests', icon: 'bug' },
  seguridad: { label: 'Safety', icon: 'shield' },
  otro: { label: 'Other', icon: 'dots' },
};

const CLOSED: ReadonlySet<StatusCode> = new Set(['resolved', 'not_applicable']);

export function isClosed(status: StatusCode): boolean {
  return CLOSED.has(status);
}

/** Priority grows with joined neighbors and severity (RF-30). */
export function priorityOf(incident: Pick<Incident, 'reportCount' | 'severity'>): number {
  return incident.reportCount * SEVERITY[incident.severity].rank;
}

/** Queue order: reopened first, then open by priority, closed last. */
export function compareForQueue(a: Incident, b: Incident): number {
  const group = (i: Incident) => (i.status === 'reopened' ? 0 : isClosed(i.status) ? 2 : 1);
  return (
    group(a) - group(b) || priorityOf(b) - priorityOf(a) || b.updatedAt.localeCompare(a.updatedAt)
  );
}

/** Status transitions an agency operator or supervisor may make from the dashboard. */
export function allowedTransitions(status: StatusCode, isSupervisor: boolean): StatusCode[] {
  switch (status) {
    case 'received':
      return isSupervisor
        ? ['sent_to_agency', 'not_applicable']
        : ['in_progress', 'not_applicable'];
    case 'sent_to_agency':
    case 'sent_by_supervisor':
      return ['in_progress', 'not_applicable'];
    case 'in_progress':
      return ['resolved'];
    case 'reopened':
      return ['in_progress'];
    case 'resolved':
    case 'not_applicable':
      return isSupervisor ? ['reopened'] : [];
  }
}
