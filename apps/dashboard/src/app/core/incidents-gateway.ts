import { Signal } from '@angular/core';
import {
  Agency,
  GatewayEvent,
  Incident,
  LatLng,
  OutboundMessage,
  StatusChangeInput,
  StatusCode,
} from './models';

export type GatewayState = 'idle' | 'loading' | 'ready' | 'error';

/**
 * Port between the dashboard and its data source.
 * Live: AppSyncIncidentsGateway (Cognito + AppSync + real-time subscription).
 * Local fallback: SyntheticIncidentsGateway (in memory, labeled as simulated).
 */
export abstract class IncidentsGateway {
  /** True when the data is synthetic; the UI then labels it as simulated. */
  abstract readonly simulated: boolean;
  abstract readonly incidents: Signal<readonly Incident[]>;
  abstract readonly agencies: Signal<readonly Agency[]>;
  /** Outbound WhatsApp messages, newest last (phone mirror; synthetic only). */
  abstract readonly messages: Signal<readonly OutboundMessage[]>;
  /** Last state change, for motion: ripple, reorder, marker drop. */
  abstract readonly lastEvent: Signal<GatewayEvent | null>;
  abstract readonly state: Signal<GatewayState>;
  abstract readonly error: Signal<string | null>;

  /** Loads the first data and starts real-time updates. Safe to call more than once. */
  abstract start(): Promise<void>;
  /** Stops real-time updates (sign-out). */
  abstract stop(): void;
  /** Fetches neighbors and timeline for one incident. */
  abstract loadDetail(incidentId: string): Promise<void>;

  /** Changes the status and resolves with the number of neighbors notified. */
  abstract changeStatus(
    incidentId: string,
    to: StatusCode,
    input: StatusChangeInput,
  ): Promise<number>;
  abstract addComment(incidentId: string, text: string, actor: string): Promise<void>;
  abstract escalate(incidentId: string, actor: string): Promise<void>;

  agencyName(agencyId: string | null | undefined): string {
    if (!agencyId) return 'Not routed yet';
    return this.agencies().find((a) => a.id === agencyId)?.name ?? agencyId;
  }
}

/** Demo controls only the in-browser synthetic data set supports. */
export interface DemoControls {
  reset(): void;
  simulateNeighborJoin(incidentId: string): void;
  simulateNewReport(): void;
  sendFollowUpNow(incidentId: string): void;
  replyToFollowUp(incidentId: string, fixed: boolean): void;
}

/** Demo controls on the real backend (admin only): synthetic rows around a point. */
export interface LiveDemoControls {
  seedDemoAt(point: LatLng): Promise<number>;
  resetDemo(): Promise<number>;
}

export function hasDemoControls(
  gateway: IncidentsGateway,
): gateway is IncidentsGateway & DemoControls {
  return typeof (gateway as Partial<DemoControls>).simulateNewReport === 'function';
}

export function hasLiveDemoControls(
  gateway: IncidentsGateway,
): gateway is IncidentsGateway & LiveDemoControls {
  return typeof (gateway as Partial<LiveDemoControls>).seedDemoAt === 'function';
}
