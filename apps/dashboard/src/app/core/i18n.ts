import { Injectable, Pipe, PipeTransform, computed, effect, inject, signal } from '@angular/core';

export type Lang = 'en' | 'es';

const STORAGE_KEY = 'urbanbot.lang';

type Dictionary = Record<string, string>;

/* English is the default dashboard language; es-MX is for Mexican officials. */
const EN: Dictionary = {
  'lang.label': 'Language',
  'lang.en': 'EN',
  'lang.es': 'ES',
  'lang.switch': 'Switch language to {lang}',

  'status.received': 'Received',
  'status.sent_to_agency': 'Sent to agency',
  'status.in_progress': 'In progress',
  'status.resolved': 'Resolved',
  'status.not_applicable': 'Not applicable',
  'status.reopened': 'Reopened',
  'status.aria': 'Status: {status}',

  'action.received.button': 'Mark received',
  'action.received.done': 'Marked received',
  'action.sent_to_agency.button': 'Send to agency',
  'action.sent_to_agency.done': 'Sent to agency',
  'action.in_progress.button': 'Mark in progress',
  'action.in_progress.done': 'Marked in progress',
  'action.resolved.button': 'Mark resolved',
  'action.resolved.done': 'Marked resolved',
  'action.not_applicable.button': 'Mark not applicable',
  'action.not_applicable.done': 'Marked not applicable',
  'action.reopened.button': 'Reopen',
  'action.reopened.done': 'Reopened',

  'severity.low': 'Low',
  'severity.medium': 'Medium',
  'severity.high': 'High',
  'severity.critical': 'Critical',
  'severity.aria': 'Severity {severity}',

  'category.agua': 'Water leak',
  'category.bacheo': 'Pothole',
  'category.alumbrado': 'Street lighting',
  'category.basura': 'Trash',
  'category.drenaje': 'Drainage',
  'category.arbol': 'Fallen tree',
  'category.plagas': 'Pests',
  'category.seguridad': 'Safety',
  'category.otro': 'Other',

  'title.at': '{category} at {place}',
  'title.near': '{category} near {place}',
  'title.nearYou': '{category} near you',
  'title.nearDemo': '{category} near the demo point',
  'title.agua': 'Water leak',
  'title.bacheo': 'Pothole',
  'title.alumbrado': 'Street lights out',
  'title.basura': 'Overflowing bins',
  'title.drenaje': 'Blocked storm drain',

  'neighbors.count': '{count} neighbors joined',
  'neighbors.one': 'neighbor',
  'neighbors.many': 'neighbors',

  'time.justNow': 'just now',
  'time.minutes': '{n} min ago',
  'time.hours': '{n} h ago',
  'time.days': '{n} d ago',

  'shell.home': 'UrbanBot home',
  'shell.nav': 'Main',
  'shell.incidents': 'Incidents',
  'shell.demo': 'Demo console',
  'shell.yourLocation': 'Your location',
  'shell.simulated': 'Simulated data',
  'shell.simulatedTitle': 'Synthetic data set; every agency is simulated',
  'shell.phone': 'Phone',
  'shell.phoneAria': "Show the neighbor's WhatsApp",
  'shell.toLight': 'Switch to light theme',
  'shell.toDark': 'Switch to dark theme',
  'shell.allAgencies': 'All agencies',
  'shell.signOut': 'Sign out',
  'shell.phoneDock': "Neighbor's WhatsApp",

  'signin.tagline': 'Neighborhood reports over WhatsApp that actually get closed.',
  'signin.footer': "Officials' dashboard · the map opens where you are",
  'signin.title': 'Sign in to the dashboard',
  'signin.lead':
    'Use the e-mail your administrator registered. Your group decides which incidents you see.',
  'signin.email': 'E-mail',
  'signin.password': 'Password',
  'signin.submit': 'Sign in',
  'signin.submitting': 'Signing in…',
  'signin.newTitle': 'Choose your password',
  'signin.newLead': 'This is your first sign-in. Replace the temporary password with your own.',
  'signin.newPassword': 'New password',
  'signin.confirmPassword': 'Confirm new password',
  'signin.policy':
    'At least 12 characters, with upper and lower case letters, a number and a symbol.',
  'signin.save': 'Save password and sign in',
  'signin.saving': 'Saving…',
  'signin.show': 'Show password',
  'signin.hide': 'Hide password',
  'signin.demoLead':
    'No backend is configured for this build, so it runs on synthetic data around your location ({place} if the browser does not share it). Choose a demo account.',
  'signin.continueAs': 'Continue as {role}',
  'signin.demoNote':
    'Every agency in this mode is simulated, and changes are labeled as simulated.',
  'signin.role.agency': 'agency operator',
  'signin.role.agencyDesc':
    'Organismo de Agua. Works the incidents routed to the agency and updates their status.',
  'signin.role.official': 'municipal supervisor',
  'signin.role.officialDesc': 'All agencies. Catches stale and reopened cases and escalates them.',
  'signin.role.admin': 'demo presenter',
  'signin.role.adminDesc': 'Supervisor access plus the demo console and the WhatsApp phone mirror.',
  'signin.err.mismatch': 'The two passwords do not match. Type the same password in both fields.',
  'signin.err.noRole':
    'Your account has no dashboard role yet. Ask an administrator to add you to the agency, official or admin group.',
  'signin.err.step':
    'This account needs a sign-in step the dashboard does not support yet. Contact an administrator.',
  'signin.err.credentials': 'The e-mail or password is incorrect. Check them and try again.',
  'signin.err.policy':
    'The new password must have at least 12 characters, with upper and lower case letters, a number and a symbol.',
  'signin.err.already': 'You are already signed in. Reload the page.',
  'signin.err.generic': 'Sign-in failed. Check your connection and try again.',

  'incidents.title': 'Incidents',
  'incidents.open': 'Open',
  'incidents.inProgress': 'In progress',
  'incidents.resolvedToday': 'Resolved today',
  'incidents.waiting': 'Neighbors waiting',
  'incidents.filters': 'Filters',
  'incidents.filterStatus': 'Status',
  'incidents.filterCategory': 'Category',
  'incidents.filterOpen': 'Open',
  'incidents.filterClosed': 'Closed',
  'incidents.filterAll': 'All',
  'incidents.agency': 'Agency',
  'incidents.allAgencies': 'All agencies',
  'incidents.queue': 'Incident queue, highest priority first',
  'incidents.escalated': 'Escalated',
  'incidents.loading': 'Loading incidents…',
  'incidents.loadError': 'The incidents could not be loaded. {error}',
  'incidents.retry': 'Try again',
  'incidents.empty':
    'No incidents yet. Reports sent to the WhatsApp number appear here in real time.',
  'incidents.noMatch': 'No incidents match these filters. Choose "All" to see closed ones too.',
  'incidents.details': 'Incident details',
  'incidents.toastSim': '{done} · {count} neighbors notified',
  'incidents.toastLive': '{done} · WhatsApp update sent to {count} neighbors',
  'incidents.saveError': 'The status was not saved. {detail}',
  'incidents.saveErrorFallback': 'Check your connection and try again.',

  'detail.close': 'Close details',
  'detail.case': 'Case',
  'detail.agency': 'Agency',
  'detail.updated': 'Updated',
  'detail.notRouted': 'Not routed yet',
  'detail.nextAction': 'Next action',
  'detail.willNotify': '{count} neighbors will be notified on WhatsApp',
  'detail.waitingFollowUp': 'Waiting for neighbors to answer "Is it fixed?", sent in {delay}.',
  'detail.waitingFollowUpUnscheduled': 'Waiting for neighbors to answer "Is it fixed?".',
  'detail.noAction': 'No status change is available for your role.',
  'detail.addComment': 'Add comment',
  'detail.escalate': 'Escalate',
  'detail.comment': 'Comment',
  'detail.commentPlaceholder': 'Visible to staff only',
  'detail.saveComment': 'Save comment',
  'detail.photos': 'Photos',
  'detail.photosNote': 'faces and plates blurred',
  'detail.photoAria': 'Blurred photo {n}',
  'detail.history': 'Status history',
  'detail.neighbors': 'Joined neighbors',
  'detail.privacy': 'Phone numbers stay masked. Saved places are never shown here.',

  'source.whatsapp': 'WhatsApp',
  'source.dashboard': 'Dashboard',
  'source.routing': 'Routing rule',
  'source.email': 'Email',
  'source.bot': 'Bot',
  'source.simulated': 'Simulated',

  'timeline.status': 'Marked {status} by {actor}',
  'timeline.statusReason': 'Marked {status} by {actor}. Reason: {reason}',
  'timeline.statusNoActor': 'Status changed to {status}',
  'timeline.firstReport': 'First report received from WhatsApp',
  'timeline.joined': 'A neighbor joined from WhatsApp',
  'timeline.joinedMany': '{n} neighbors joined from WhatsApp',
  'timeline.routed': 'Assigned to {agency} by routing rule; agency email pending',
  'timeline.routedMailed': 'Assigned to {agency} by routing rule; agency email sent',
  'timeline.agencyEmailSent': 'Agency email sent to {agency}',
  'timeline.agencyEmailSentNoName': 'Agency email sent',
  'timeline.supervisorEmailSent': 'Email sent to the supervisor',
  'timeline.escalated': 'Escalated to the next level of government',
  'timeline.notified': '{n} neighbors notified on WhatsApp',
  'timeline.followUpScheduled': '"Is it fixed?" scheduled for neighbors in {delay}',
  'timeline.followUpSent': '"Is it fixed?" sent to {n} neighbors',
  'timeline.replyNo': 'A neighbor answered "No, sigue igual": the incident is reopened',
  'timeline.replyYes': 'A neighbor confirmed it is fixed',

  'dialog.cancel': 'Cancel',
  'dialog.reason': 'Reason (required, sent to neighbors)',
  'dialog.chooseReason': 'Choose a reason',
  'dialog.comment': 'Comment for the timeline (optional, not sent)',
  'dialog.commentPlaceholder': 'What did the crew find or do?',
  'dialog.preview': 'WhatsApp message preview',
  'dialog.recipients': '{count} neighbors will receive on WhatsApp',
  'dialog.previewHint':
    'Sent within a minute. After the 24 h window, an approved template is used.',
  'dialog.reason.private': 'Private property',
  'dialog.reason.duplicate': 'Duplicate of another incident',
  'dialog.reason.notMunicipal': 'Not a municipal responsibility',
  'dialog.reason.notFound': 'Could not be located',

  'map.aria': 'Map of incidents',
  'map.showAll': 'Show all incidents',
  'map.myLocation': 'My location',
  'map.legendSize': 'Size: neighbors joined',
  'map.legendColor': 'Color and glyph: status',
  'map.legendEscalated': 'Escalated',
  'map.fallback': 'Local tiles · Amazon Location in deployed builds',
  'map.markerAria': '{title}. {status}. {count} neighbors joined.',

  'demo.title': 'Demo console',
  'demo.lead':
    'Plays the end-to-end loop on the data around you: {reports} reports in {incidents} incidents. Every agency action here is simulated and labeled as simulated.',
  'demo.load': 'Load demo data here',
  'demo.loading': 'Loading…',
  'demo.loadLead':
    'Writes 30 synthetic reports in 4 incidents around {where}, flagged as synthetic. Real WhatsApp reports appear alongside them.',
  'demo.whereDevice': 'your current location',
  'demo.whereDefault': 'the default center',
  'demo.story': 'Story incident',
  'demo.open': 'Open in the dashboard',
  'demo.run': 'Run',
  'demo.reset': 'Reset demo data',
  'demo.resetLead': 'Restores the demo incidents and clears the phone.',
  'demo.unavailable': 'The demo console works only with demo data.',
  'demo.liveTitle': 'WhatsApp side',
  'demo.liveText':
    'Status changes here publish StatusChanged to the notifier, which sends the update through AWS End User Messaging Social. Show the phone of a neighbor next to this screen to record both sides of the loop.',
  'demo.liveAria': 'WhatsApp side of the demo',
  'demo.toastLoaded': 'Demo data loaded here · {count} incidents from 30 synthetic reports',
  'demo.toastLoadFailed': 'Demo data was not loaded. {detail}',
  'demo.toastRemoved': 'Demo data removed · {count} synthetic incidents deleted',
  'demo.toastRemoveFailed': 'Demo data was not removed. {detail}',
  'demo.toastReset': 'Demo reset · 30 reports in 4 incidents',
  'demo.step.newReport': 'A new report arrives',
  'demo.step.newReportDetail':
    'A neighbor nearby sends a photo of a blocked storm drain. Its geohash cell lights up and the marker lands on the map.',
  'demo.step.join': 'A neighbor joins the water leak',
  'demo.step.joinDetail':
    'Instead of a duplicate ticket, the report joins the incident: the counter ticks up and the leak climbs the queue.',
  'demo.step.inProgress': 'The water agency starts work',
  'demo.step.inProgressDetail':
    'The simulated agency marks the leak in progress. Every joined neighbor gets the update on WhatsApp in under a minute.',
  'demo.step.resolved': 'The water agency resolves it',
  'demo.step.resolvedDetail':
    'The agency marks it resolved. The bot schedules "Is it fixed?" for 24 hours later.',
  'demo.step.followUp': 'Ask the neighbors: "Is it fixed?"',
  'demo.step.followUpDetail':
    'Fast-forwards the 24 hours. Answer on the phone: "No, sigue igual" reopens the incident and alerts the agency.',

  'phone.who': 'WhatsApp of neighbor {id}',
  'phone.english': 'English',
  'phone.banner': 'Simulated · rebuilt from the messages the notifier sent',
  'phone.aria': 'WhatsApp conversation',
  'phone.empty':
    'No messages yet. Change the status of the water leak and the update arrives here.',

  'toast.dismiss': 'Dismiss',
};

const ES: Dictionary = {
  'lang.label': 'Idioma',
  'lang.en': 'EN',
  'lang.es': 'ES',
  'lang.switch': 'Cambiar idioma a {lang}',

  'status.received': 'Recibido',
  'status.sent_to_agency': 'Enviado a dependencia',
  'status.in_progress': 'En atención',
  'status.resolved': 'Resuelto',
  'status.not_applicable': 'No procede',
  'status.reopened': 'Reabierto',
  'status.aria': 'Estatus: {status}',

  'action.received.button': 'Marcar recibido',
  'action.received.done': 'Marcado como recibido',
  'action.sent_to_agency.button': 'Enviar a dependencia',
  'action.sent_to_agency.done': 'Enviado a dependencia',
  'action.in_progress.button': 'Marcar en atención',
  'action.in_progress.done': 'Marcado en atención',
  'action.resolved.button': 'Marcar resuelto',
  'action.resolved.done': 'Marcado como resuelto',
  'action.not_applicable.button': 'Marcar no procede',
  'action.not_applicable.done': 'Marcado como no procede',
  'action.reopened.button': 'Reabrir',
  'action.reopened.done': 'Reabierto',

  'severity.low': 'Baja',
  'severity.medium': 'Media',
  'severity.high': 'Alta',
  'severity.critical': 'Crítica',
  'severity.aria': 'Severidad {severity}',

  'category.agua': 'Fuga de agua',
  'category.bacheo': 'Bache',
  'category.alumbrado': 'Alumbrado',
  'category.basura': 'Basura',
  'category.drenaje': 'Drenaje',
  'category.arbol': 'Árbol caído',
  'category.plagas': 'Plagas',
  'category.seguridad': 'Seguridad',
  'category.otro': 'Otro',

  'title.at': '{category} en {place}',
  'title.near': '{category} cerca de {place}',
  'title.nearYou': '{category} cerca de ti',
  'title.nearDemo': '{category} cerca del punto de demo',
  'title.agua': 'Fuga de agua',
  'title.bacheo': 'Bache',
  'title.alumbrado': 'Luminarias apagadas',
  'title.basura': 'Contenedores llenos',
  'title.drenaje': 'Coladera tapada',

  'neighbors.count': '{count} vecinos sumados',
  'neighbors.one': 'vecino',
  'neighbors.many': 'vecinos',

  'time.justNow': 'justo ahora',
  'time.minutes': 'hace {n} min',
  'time.hours': 'hace {n} h',
  'time.days': 'hace {n} d',

  'shell.home': 'Inicio de UrbanBot',
  'shell.nav': 'Principal',
  'shell.incidents': 'Incidentes',
  'shell.demo': 'Consola de demo',
  'shell.yourLocation': 'Tu ubicación',
  'shell.simulated': 'Datos simulados',
  'shell.simulatedTitle': 'Datos sintéticos; todas las dependencias son simuladas',
  'shell.phone': 'Teléfono',
  'shell.phoneAria': 'Mostrar el WhatsApp del vecino',
  'shell.toLight': 'Cambiar a tema claro',
  'shell.toDark': 'Cambiar a tema oscuro',
  'shell.allAgencies': 'Todas las dependencias',
  'shell.signOut': 'Cerrar sesión',
  'shell.phoneDock': 'WhatsApp del vecino',

  'signin.tagline': 'Reportes vecinales por WhatsApp que sí se cierran.',
  'signin.footer': 'Panel de funcionarios · el mapa abre donde estás',
  'signin.title': 'Inicia sesión en el panel',
  'signin.lead': 'Usa el correo que registró tu administrador. Tu grupo define qué incidentes ves.',
  'signin.email': 'Correo',
  'signin.password': 'Contraseña',
  'signin.submit': 'Iniciar sesión',
  'signin.submitting': 'Iniciando sesión…',
  'signin.newTitle': 'Elige tu contraseña',
  'signin.newLead': 'Es tu primer inicio de sesión. Cambia la contraseña temporal por una tuya.',
  'signin.newPassword': 'Contraseña nueva',
  'signin.confirmPassword': 'Confirma la contraseña nueva',
  'signin.policy': 'Mínimo 12 caracteres, con mayúsculas, minúsculas, un número y un símbolo.',
  'signin.save': 'Guardar contraseña y entrar',
  'signin.saving': 'Guardando…',
  'signin.show': 'Mostrar contraseña',
  'signin.hide': 'Ocultar contraseña',
  'signin.demoLead':
    'Este build no tiene backend configurado, así que usa datos sintéticos alrededor de tu ubicación ({place} si el navegador no la comparte). Elige una cuenta demo.',
  'signin.continueAs': 'Continuar como {role}',
  'signin.demoNote':
    'En este modo todas las dependencias son simuladas y los cambios se marcan como simulados.',
  'signin.role.agency': 'operador de dependencia',
  'signin.role.agencyDesc':
    'Organismo de Agua. Atiende los incidentes asignados a la dependencia y actualiza su estatus.',
  'signin.role.official': 'supervisor municipal',
  'signin.role.officialDesc':
    'Todas las dependencias. Detecta casos estancados o reabiertos y los escala.',
  'signin.role.admin': 'presentador de demo',
  'signin.role.adminDesc': 'Acceso de supervisor más la consola de demo y el espejo del WhatsApp.',
  'signin.err.mismatch': 'Las contraseñas no coinciden. Escribe la misma en ambos campos.',
  'signin.err.noRole':
    'Tu cuenta aún no tiene rol en el panel. Pide a un administrador que te agregue al grupo agency, official o admin.',
  'signin.err.step':
    'Esta cuenta requiere un paso de inicio de sesión que el panel aún no soporta. Contacta a un administrador.',
  'signin.err.credentials':
    'El correo o la contraseña no son correctos. Revísalos e inténtalo de nuevo.',
  'signin.err.policy':
    'La contraseña nueva debe tener mínimo 12 caracteres, con mayúsculas, minúsculas, un número y un símbolo.',
  'signin.err.already': 'Ya tienes una sesión iniciada. Recarga la página.',
  'signin.err.generic': 'No se pudo iniciar sesión. Revisa tu conexión e inténtalo de nuevo.',

  'incidents.title': 'Incidentes',
  'incidents.open': 'Abiertos',
  'incidents.inProgress': 'En atención',
  'incidents.resolvedToday': 'Resueltos hoy',
  'incidents.waiting': 'Vecinos esperando',
  'incidents.filters': 'Filtros',
  'incidents.filterStatus': 'Estatus',
  'incidents.filterCategory': 'Categoría',
  'incidents.filterOpen': 'Abiertos',
  'incidents.filterClosed': 'Cerrados',
  'incidents.filterAll': 'Todos',
  'incidents.agency': 'Dependencia',
  'incidents.allAgencies': 'Todas las dependencias',
  'incidents.queue': 'Fila de incidentes, primero los de mayor prioridad',
  'incidents.escalated': 'Escalado',
  'incidents.loading': 'Cargando incidentes…',
  'incidents.loadError': 'No se pudieron cargar los incidentes. {error}',
  'incidents.retry': 'Reintentar',
  'incidents.empty':
    'Aún no hay incidentes. Los reportes que lleguen al número de WhatsApp aparecen aquí en tiempo real.',
  'incidents.noMatch':
    'Ningún incidente coincide con los filtros. Elige "Todos" para ver también los cerrados.',
  'incidents.details': 'Detalle del incidente',
  'incidents.toastSim': '{done} · {count} vecinos avisados',
  'incidents.toastLive': '{done} · aviso por WhatsApp enviado a {count} vecinos',
  'incidents.saveError': 'No se guardó el estatus. {detail}',
  'incidents.saveErrorFallback': 'Revisa tu conexión e inténtalo de nuevo.',

  'detail.close': 'Cerrar detalle',
  'detail.case': 'Folio',
  'detail.agency': 'Dependencia',
  'detail.updated': 'Actualizado',
  'detail.notRouted': 'Sin asignar todavía',
  'detail.nextAction': 'Siguiente acción',
  'detail.willNotify': 'Se avisará por WhatsApp a {count} vecinos',
  'detail.waitingFollowUp':
    'Esperando que los vecinos respondan "¿Ya quedó?", que se envía en {delay}.',
  'detail.waitingFollowUpUnscheduled': 'Esperando que los vecinos respondan "¿Ya quedó?".',
  'detail.noAction': 'Tu rol no tiene cambios de estatus disponibles.',
  'detail.addComment': 'Agregar comentario',
  'detail.escalate': 'Escalar',
  'detail.comment': 'Comentario',
  'detail.commentPlaceholder': 'Visible solo para el personal',
  'detail.saveComment': 'Guardar comentario',
  'detail.photos': 'Fotos',
  'detail.photosNote': 'rostros y placas difuminados',
  'detail.photoAria': 'Foto difuminada {n}',
  'detail.history': 'Historial de estatus',
  'detail.neighbors': 'Vecinos sumados',
  'detail.privacy':
    'Los teléfonos se muestran enmascarados. Los lugares guardados nunca aparecen aquí.',

  'source.whatsapp': 'WhatsApp',
  'source.dashboard': 'Panel',
  'source.routing': 'Regla de ruteo',
  'source.email': 'Correo',
  'source.bot': 'Bot',
  'source.simulated': 'Simulado',

  'timeline.status': 'Marcado {status} por {actor}',
  'timeline.statusReason': 'Marcado {status} por {actor}. Motivo: {reason}',
  'timeline.statusNoActor': 'Estatus cambiado a {status}',
  'timeline.firstReport': 'Primer reporte recibido por WhatsApp',
  'timeline.joined': 'Un vecino se sumó por WhatsApp',
  'timeline.joinedMany': '{n} vecinos se sumaron por WhatsApp',
  'timeline.routed': 'Turnado a {agency} por regla de ruteo; correo a la dependencia pendiente',
  'timeline.routedMailed': 'Turnado a {agency} por regla de ruteo; correo a la dependencia enviado',
  'timeline.agencyEmailSent': 'Correo enviado a {agency}',
  'timeline.agencyEmailSentNoName': 'Correo enviado a la dependencia',
  'timeline.supervisorEmailSent': 'Correo enviado al supervisor',
  'timeline.escalated': 'Escalado al siguiente nivel de gobierno',
  'timeline.notified': '{n} vecinos avisados por WhatsApp',
  'timeline.followUpScheduled': '"¿Ya quedó?" programado para los vecinos en {delay}',
  'timeline.followUpSent': '"¿Ya quedó?" enviado a {n} vecinos',
  'timeline.replyNo': 'Un vecino respondió "No, sigue igual": el incidente se reabre',
  'timeline.replyYes': 'Un vecino confirmó que ya quedó',

  'dialog.cancel': 'Cancelar',
  'dialog.reason': 'Motivo (obligatorio, se envía a los vecinos)',
  'dialog.chooseReason': 'Elige un motivo',
  'dialog.comment': 'Comentario para el historial (opcional, no se envía)',
  'dialog.commentPlaceholder': '¿Qué encontró o hizo la cuadrilla?',
  'dialog.preview': 'Vista previa del mensaje de WhatsApp',
  'dialog.recipients': '{count} vecinos recibirán por WhatsApp',
  'dialog.previewHint':
    'Se envía en menos de un minuto. Después de la ventana de 24 h se usa una plantilla aprobada.',
  'dialog.reason.private': 'Propiedad privada',
  'dialog.reason.duplicate': 'Duplicado de otro incidente',
  'dialog.reason.notMunicipal': 'No es competencia municipal',
  'dialog.reason.notFound': 'No se pudo ubicar',

  'map.aria': 'Mapa de incidentes',
  'map.showAll': 'Ver todos los incidentes',
  'map.myLocation': 'Mi ubicación',
  'map.legendSize': 'Tamaño: vecinos sumados',
  'map.legendColor': 'Color e ícono: estatus',
  'map.legendEscalated': 'Escalado',
  'map.fallback': 'Mapa local · Amazon Location en el sitio publicado',
  'map.markerAria': '{title}. {status}. {count} vecinos sumados.',

  'demo.title': 'Consola de demo',
  'demo.lead':
    'Reproduce el ciclo completo con los datos a tu alrededor: {reports} reportes en {incidents} incidentes. Toda acción de dependencia aquí es simulada y se marca como simulada.',
  'demo.load': 'Cargar datos demo aquí',
  'demo.loading': 'Cargando…',
  'demo.loadLead':
    'Crea 30 reportes sintéticos en 4 incidentes alrededor de {where}, marcados como sintéticos. Los reportes reales de WhatsApp aparecen junto a ellos.',
  'demo.whereDevice': 'tu ubicación actual',
  'demo.whereDefault': 'el centro por defecto',
  'demo.story': 'Incidente de la historia',
  'demo.open': 'Abrir en el panel',
  'demo.run': 'Ejecutar',
  'demo.reset': 'Reiniciar datos demo',
  'demo.resetLead': 'Restaura los incidentes demo y limpia el teléfono.',
  'demo.unavailable': 'La consola de demo solo funciona con datos demo.',
  'demo.liveTitle': 'Lado de WhatsApp',
  'demo.liveText':
    'Los cambios de estatus aquí publican StatusChanged al notifier, que envía el aviso por AWS End User Messaging Social. Muestra el teléfono de un vecino junto a esta pantalla para grabar ambos lados del ciclo.',
  'demo.liveAria': 'Lado de WhatsApp de la demo',
  'demo.toastLoaded': 'Datos demo cargados aquí · {count} incidentes con 30 reportes sintéticos',
  'demo.toastLoadFailed': 'No se cargaron los datos demo. {detail}',
  'demo.toastRemoved': 'Datos demo eliminados · {count} incidentes sintéticos borrados',
  'demo.toastRemoveFailed': 'No se eliminaron los datos demo. {detail}',
  'demo.toastReset': 'Demo reiniciada · 30 reportes en 4 incidentes',
  'demo.step.newReport': 'Llega un reporte nuevo',
  'demo.step.newReportDetail':
    'Un vecino cercano envía la foto de una coladera tapada. Su celda de geohash se ilumina y el marcador cae en el mapa.',
  'demo.step.join': 'Un vecino se suma a la fuga de agua',
  'demo.step.joinDetail':
    'En lugar de un ticket duplicado, el reporte se suma al incidente: el contador sube y la fuga escala en la fila.',
  'demo.step.inProgress': 'La dependencia de agua empieza a trabajar',
  'demo.step.inProgressDetail':
    'La dependencia simulada marca la fuga en atención. Cada vecino sumado recibe el aviso por WhatsApp en menos de un minuto.',
  'demo.step.resolved': 'La dependencia de agua la resuelve',
  'demo.step.resolvedDetail':
    'La dependencia la marca como resuelta. El bot programa "¿Ya quedó?" para 24 horas después.',
  'demo.step.followUp': 'Preguntar a los vecinos: "¿Ya quedó?"',
  'demo.step.followUpDetail':
    'Adelanta las 24 horas. Responde en el teléfono: "No, sigue igual" reabre el incidente y avisa a la dependencia.',

  'phone.who': 'WhatsApp del vecino {id}',
  'phone.english': 'Inglés',
  'phone.banner': 'Simulado · reconstruido a partir de los mensajes que envió el notifier',
  'phone.aria': 'Conversación de WhatsApp',
  'phone.empty': 'Aún no hay mensajes. Cambia el estatus de la fuga de agua y el aviso llega aquí.',

  'toast.dismiss': 'Cerrar',
};

const DICTIONARIES: Record<Lang, Dictionary> = { en: EN, es: ES };

/** Keys of the English dictionary; ES must define the same set (checked in tests). */
export const I18N_KEYS = Object.keys(EN);
export const I18N_DICTIONARIES = DICTIONARIES;

function readSaved(): Lang {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'es' ? 'es' : 'en';
  } catch {
    return 'en';
  }
}

export function interpolate(template: string, params?: Record<string, string | number>): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    params[name] !== undefined ? String(params[name]) : match,
  );
}

/**
 * Dashboard language (English by default, Spanish for Mexican officials).
 * Switching is instant: every template reads translations through signals.
 */
@Injectable({ providedIn: 'root' })
export class I18nService {
  readonly lang = signal<Lang>(readSaved());
  readonly locale = computed(() => (this.lang() === 'es' ? 'es-MX' : 'en-US'));

  constructor() {
    effect(() => {
      const lang = this.lang();
      document.documentElement.lang = lang;
      try {
        localStorage.setItem(STORAGE_KEY, lang);
      } catch {
        /* Storage unavailable; the choice lasts for this visit. */
      }
    });
  }

  set(lang: Lang): void {
    this.lang.set(lang);
  }

  t(key: string, params?: Record<string, string | number>): string {
    const template = DICTIONARIES[this.lang()][key] ?? EN[key] ?? key;
    return interpolate(template, params);
  }
}

/** `{{ 'shell.incidents' | t }}` or `{{ 'detail.willNotify' | t: { count: 12 } }}`. */
@Pipe({ name: 't', pure: false })
export class TranslatePipe implements PipeTransform {
  private readonly i18n = inject(I18nService);

  transform(key: string, params?: Record<string, string | number>): string {
    return this.i18n.t(key, params);
  }
}
