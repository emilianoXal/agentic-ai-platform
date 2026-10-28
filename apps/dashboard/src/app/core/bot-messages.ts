import { formatClockEs } from './format';
import { STATUS } from './labels';
import { Incident, StatusCode } from './models';

/**
 * WhatsApp copy the notifier sends, in es-MX, with an English gloss for the
 * presenter and the judges. Mirrors the voice rules in the design system:
 * at most two lines, always the next step, never an invented status.
 */
export interface BotCopy {
  readonly es: string;
  readonly en: string;
}

export function statusMessage(
  incident: Incident,
  status: StatusCode,
  agencyName: string,
  at: string,
  reason?: string,
): BotCopy {
  const emoji = STATUS[status].emoji;
  const folio = incident.folio;
  switch (status) {
    case 'sent_to_agency':
      return {
        es: `${emoji} Tu reporte ${folio} ya está con ${agencyName}. Te aviso en cuanto cambie.`,
        en: `Your report ${folio} is now with ${agencyName}. I'll message you as soon as it changes.`,
      };
    case 'in_progress':
      return {
        es: `${emoji} Tu reporte ${folio} está en atención. ${agencyName} lo actualizó hoy a las ${formatClockEs(at)}.`,
        en: `Your report ${folio} is in progress. ${agencyName} updated it today at ${formatClockEs(at)}.`,
      };
    case 'resolved':
      return {
        es: `${emoji} ${agencyName} marcó ${incident.titleEs} como resuelta. Mañana te pregunto si ya quedó.`,
        en: `${agencyName} marked the incident as resolved. Tomorrow I'll ask you if it's fixed.`,
      };
    case 'not_applicable':
      return {
        es: `${emoji} ${agencyName} indicó que tu reporte ${folio} no procede: ${reason ?? 'sin motivo registrado'}. Escribe «asesor» si quieres hablar con una persona.`,
        en: `${agencyName} said report ${folio} doesn't apply: ${reason ?? 'no reason recorded'}. Type "asesor" to talk to a person.`,
      };
    case 'reopened':
      return {
        es: `${emoji} Reabrimos tu reporte ${folio} y avisamos a ${agencyName}.`,
        en: `We reopened your report ${folio} and told ${agencyName}.`,
      };
    case 'received':
      return {
        es: `${emoji} Recibimos tu reporte ${folio}. Te aviso cuando cambie.`,
        en: `We received your report ${folio}. I'll message you when it changes.`,
      };
  }
}

export function followUpMessage(incident: Incident, agencyName: string): BotCopy {
  return {
    es: `¿Ya quedó? ${agencyName} dice que resolvió ${incident.titleEs}.`,
    en: `Is it fixed? ${agencyName} says it resolved the incident.`,
  };
}

export const FOLLOW_UP_REPLIES = {
  fixed: { es: 'Sí, ya quedó', en: "Yes, it's fixed" },
  notFixed: { es: 'No, sigue igual', en: 'No, still the same' },
} as const;
