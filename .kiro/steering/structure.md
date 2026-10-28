---
inclusion: always
---

# Estructura del repositorio y estado actual

Este es un repositorio **solo de infraestructura (Terraform)**. El código de
aplicación de las Lambdas vive junto a su módulo, en `modules/<modulo>/src/`.

## Layout del monorepo

```
agentic-ai-platform/
├── .gitlab-ci.yml            # Pipeline OIDC (validate / plan / apply / destroy / untaint)
├── .gitignore                # Ignora .terraform/, state, zips de build/, .agents/
├── .terraform-version        # 1.10
├── .kiro/steering/           # Contexto para Kiro/IA (estos archivos)
├── envs/                     # Una carpeta por entorno; cada una es una raíz Terraform
│   ├── dev/                  # backend.tf, main.tf, variables.tf, outputs.tf, versions.tf, terraform.tfvars
│   ├── qa/                   # Espeja a dev con su propio backend key
│   └── prod/                 # Espeja a dev con su propio backend key
└── modules/                  # Módulos reutilizables, uno por dominio del diagrama
    ├── data/                 # [LISTO] Capa de datos + bus de eventos
    ├── compute/              # [LISTO] Glue de ingesta (Lambdas ingest + notifier)
    ├── agent/                # [LISTO] Tool Lambdas + consumer + AgentCore
    ├── media/                # [PENDIENTE] Pipeline de medios (Rekognition/Transcribe/Nova)
    └── portal/               # [PENDIENTE] Dashboard (Amplify/Cognito/AppSync/WAF)
```

Cada `envs/<env>/` es una **raíz Terraform independiente** con su propio state
(aislado por backend key). Los módulos NO se aplican solos: se invocan desde
`envs/<env>/main.tf`.

## Patrón de dependencia entre módulos

Los módulos **no se alcanzan entre sí** (`module.data.*` nunca aparece dentro de
otro módulo). El entorno (`envs/<env>/main.tf`) toma los outputs de un módulo y
los pasa como variables explícitas al siguiente, con los **nombres reales de
output 1:1** (sin renombrar). Ejemplo:

```hcl
module "agent" {
  source               = "../../modules/agent"
  environment          = var.environment
  kms_key_arn          = module.data.kms_key_arn
  incidents_table_arn  = module.data.incidents_table_arn
  # ...
}
```

## Qué se ha construido (estado por módulo)

### modules/data — LISTO
- KMS CMK (rotación + alias) que cifra S3, DynamoDB, SNS, SQS.
- S3 `media` bucket: SSE-KMS, versioning, public-access-block, lifecycle de
  retención en `raw/`, BucketOwnerEnforced.
- 5 tablas DynamoDB (PAY_PER_REQUEST, CMK, PITR):
  - `reports` (PK report_id; GSI `by-user`) — streams NEW_AND_OLD_IMAGES
  - `incidents` (PK incident_id; GSI `by-geohash`) — streams NEW_AND_OLD_IMAGES
  - `places` (PK user_id, SK place_id) — SIN GSI
  - `users` (PK user_id) — consentimiento/opt-in + preferencias
  - `audit-log` (PK entity_id, SK ts) — bitácora append-only (RF-15)
- SNS topic `inbound` (cifrado CMK).
- SQS FIFO `ingest` + DLQ (content-based dedup, redrive maxReceiveCount=5).
- EventBridge bus `events`.

### modules/compute — LISTO
- Lambda `ingest` (Python 3.12): SNS inbound → guards deterministas
  (idempotencia por message_id, consentimiento, rate limit, input guard) → SQS
  FIFO. Nunca descarta mensajes; anota flags.
- Lambda `notifier` (Python 3.12): EventBridge (`StatusChanged` /
  `IncidentNearby`) → quiet hours + daily cap → envío **stubeado** (TODO para el
  `SendWhatsAppMessage` real).
- IAM mínimo privilegio por Lambda.

### modules/agent — LISTO (Opción A)
- 6 Tool Lambdas (Python 3.12): `create_report`, `join_incident`, `get_status`,
  `register_place`, `route`, `escalate`.
- Lambda `consumer`: drena la SQS FIFO con contrato partial-batch-failure
  (`ReportBatchItemFailures`).
- ECR repo (para la imagen del agente Strands).
- Bedrock Guardrails (prompt-injection + temas prohibidos de WhatsApp).
- Rol de ejecución AgentCore (siempre creado).
- AgentCore Runtime/Gateway/Memory (provider `awscc`) **detrás de flags
  `enable_agentcore_*`, default false** → validate/plan no requieren imagen.

## Pendientes conocidos (TODOs arrastrados)

1. **Imagen del agente Strands** en ECR antes de `enable_agentcore_runtime=true`
   (código de aplicación, no infra).
2. `InvokeAgentRuntime` en el `consumer` (TODO gated).
3. `SendWhatsAppMessage` real en el `notifier` (hoy stub) — llega con el canal.
4. Gateway `CUSTOM_JWT` necesita `authorizer_configuration` con OIDC real.
5. Key policy de la CMK sigue en default (aceptable same-account).
6. `media` y `portal` aún no existen.

## Convención de ramas

- `main` es la rama protegida de integración. **No** se hace push directo.
- Trabaja en ramas `feat/<tema>`, `fix/<tema>`, `hotfix/<tema>`,
  `release/<tema>`. El pipeline corre validate+plan en esas ramas y deja el
  `apply` como job manual.
- Un módulo nuevo = una rama de feature + un merge request.
