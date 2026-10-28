/** The six standard incident statuses (RF-17). Escalation is a separate flag. */
export type StatusCode =
  'received' | 'sent_to_agency' | 'in_progress' | 'resolved' | 'not_applicable' | 'reopened';

export type Severity = 'low' | 'medium' | 'high' | 'critical';

/** Category codes match the routing rules used by the tool Lambdas. */
export type CategoryCode =
  | 'agua'
  | 'bacheo'
  | 'alumbrado'
  | 'basura'
  | 'drenaje'
  | 'arbol'
  | 'plagas'
  | 'seguridad'
  | 'otro';

export type Role = 'agency' | 'official' | 'admin';

/** Where a change came from; simulated changes are always labeled (RB-08). */
export type ChangeSource = 'whatsapp' | 'dashboard' | 'routing' | 'email' | 'bot' | 'simulated';

export interface Agency {
  readonly id: string;
  readonly name: string;
}

export interface LatLng {
  readonly lat: number;
  readonly lng: number;
}

export type TimelineKind =
  'status' | 'joined' | 'routed' | 'comment' | 'notified' | 'follow_up' | 'reply' | 'escalated';

export interface TimelineEntry {
  readonly id: string;
  /** UTC ISO 8601. */
  readonly at: string;
  readonly kind: TimelineKind;
  readonly text: string;
  readonly source: ChangeSource;
  readonly status?: StatusCode | null;
  readonly actor?: string | null;
}

export interface Incident {
  readonly id: string;
  readonly folio: string;
  readonly category: CategoryCode;
  readonly title: string;
  /** Spanish noun phrase the bot uses in messages, e.g. "la fuga de agua en Calle Hidalgo 214". */
  readonly titleEs: string;
  readonly neighborhood: string | null;
  readonly geohash: string;
  readonly location: LatLng;
  readonly status: StatusCode;
  readonly escalated: boolean;
  readonly severity: Severity;
  readonly reportCount: number;
  readonly agencyId: string | null;
  readonly agencyName?: string | null;
  readonly agencyCaseId?: string | null;
  readonly photoCount: number;
  /** Masked phone suffixes of everyone joined to the incident; never full numbers (RNF-10). */
  readonly neighbors: readonly string[];
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly followUpPending: boolean;
  readonly timeline: readonly TimelineEntry[];
}

export interface OutboundMessage {
  readonly id: string;
  readonly at: string;
  readonly to: string;
  readonly incidentId: string;
  readonly folio: string;
  readonly textEs: string;
  readonly textEn: string;
  readonly kind: 'status' | 'follow_up' | 'reply';
  /** True for the citizen's own replies shown in the phone mirror. */
  readonly fromCitizen?: boolean;
  readonly awaitingReply?: boolean;
}

export type GatewayEventKind =
  'status' | 'joined' | 'created' | 'removed' | 'reopened' | 'notified' | 'escalated';

export interface GatewayEvent {
  readonly kind: GatewayEventKind;
  readonly incidentId: string;
  readonly nonce: number;
  readonly count?: number;
}

export interface StatusChangeInput {
  readonly comment?: string;
  readonly reason?: string;
  readonly actor: string;
}

export interface Session {
  readonly name: string;
  readonly email?: string;
  readonly role: Role;
  /** Set for agency operators; scopes the queue to that agency. */
  readonly agencyId?: string;
}
