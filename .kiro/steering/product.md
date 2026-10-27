---
inclusion: always
---

# Producto — Bot ciudadano de infraestructura urbana (urbanbot)

## Qué es

`urbanbot` es un bot de WhatsApp que permite a cualquier persona reportar una
incidencia urbana (baches, fugas, alumbrado, basura, etc.) con fotos, ubicación
y descripción, seguirla hasta su cierre y recibir avisos de lo que ocurre cerca
de sus lugares registrados. Proyecto del Hackathon AWS CDS Agentic AI.

## Diferenciadores (no es "un formulario más")

1. **Clúster de incidentes** en lugar de tickets sueltos: la prioridad sube con
   los vecinos que se suman al mismo problema.
2. **Estatus proactivo**: el bot informa cambios y pregunta "¿ya quedó?" para
   reabrir el caso si no se resolvió.
3. **Consulta por colonia**: qué hay reportado o programado en una zona.
4. **Escalamiento por umbral** al siguiente nivel de gobierno cuando el caso no
   se atiende.

## Alcance del MVP

- Cubre los requisitos funcionales de **prioridad Alta** + los requisitos de las
  bases del hackathon. Media/Baja quedan como evolución.
- Datos **sintéticos**: un municipio ficticio, ~30 reportes simulados que
  agrupan en ~4 incidentes, 2-3 usuarios con lugares, una dependencia simulada
  que actualiza estatus desde el panel.

## Fuera de alcance

Pagos o trámites, emergencias en tiempo real (el bot NO sustituye al 911),
asistente de IA de propósito general, cobranza, integración real con APIs de
dependencias (CFE/SIAPA/etc.).

## Restricciones no negociables (bases del hackathon)

- **RB-01 (pasa/no pasa):** el código en ejecución DEBE importar y llamar el SDK
  de CDS: `socialmessaging` con `SendWhatsAppMessage` para WhatsApp, SES para
  correo. Nombrarlo en el README no cuenta.
- **RB-02:** WhatsApp entra y sale por **AWS End User Messaging Social** (premio
  Best WhatsApp Solution).
- **RB-03:** todo se construye en **us-east-1** (AgentCore y Rekognition no
  existen en mx-central-1).
- **RB-06:** el agente usa **AgentCore** con herramientas: enrutar, consultar y
  escalar.

## Requisitos transversales que todo módulo debe respetar

- **Privacidad (LFPDPPP):** aviso + consentimiento (opt-in) antes de guardar
  datos; comando de borrado; retención limitada de fotos/datos.
- **Fotos con terceros:** difuminar rostros y placas antes de exponerlas.
- **Ubicación y lugares (casa/oficina) son datos sensibles:** nunca se publican,
  no son visibles para el funcionario.
- **Prompt injection:** validaciones deterministas ANTES del modelo; el modelo
  solo propone, las acciones pasan por herramientas con permisos acotados.
- **Veracidad:** el bot no inventa estatus; si no hay dato, lo dice.
- **Idioma:** el bot atiende en español; repositorio, descripción y video en
  inglés o traducidos.

## Idioma de trabajo

Conversación y mensajes al usuario final en **español (es-MX)**. Código,
comentarios, nombres de recursos y entregables del concurso en **inglés**.
