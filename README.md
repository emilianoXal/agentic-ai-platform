# agentic-ai-platform — urbanbot infrastructure

Infrastructure as Code (Terraform) for **urbanbot**, a WhatsApp citizen bot for
urban infrastructure reporting. Built for the AWS CDS Agentic AI Hackathon.

Citizens report urban issues (potholes, leaks, lighting, trash, etc.) over
WhatsApp with photos, location and description; the bot clusters nearby reports
into incidents, tracks status proactively, escalates stale cases, and notifies
neighbors about issues near their registered places.

- **AWS account:** `636487155766` (aws-xaldigital-hackathon-agentic)
- **Region:** `us-east-1` (required — AgentCore and Rekognition are not in
  mx-central-1)
- **IaC:** Terraform 1.10, providers `aws ~> 5.0`, `archive ~> 2.0`,
  `awscc ~> 1.0`
- **Architecture:** Proposal 1 — event-driven serverless + Amazon Bedrock
  AgentCore

> New to the repo? Read [`CONTRIBUTING.md`](CONTRIBUTING.md) for conventions and
> how to add a module. If you use the Kiro IDE, the `.kiro/steering/` files load
> this context automatically.

## Repository layout

```
envs/<env>/        # dev | qa | prod — each is an isolated Terraform root (own state)
modules/data/      # [done] KMS CMK, S3 media, 5 DynamoDB tables, SNS, SQS FIFO, EventBridge
modules/compute/   # [done] ingest + notifier Lambdas (ingestion glue)
modules/agent/     # [done] 6 tool Lambdas, SQS consumer, ECR, Guardrails, AgentCore (awscc)
modules/media/     # [todo] Rekognition blur + Transcribe + Nova multimodal
modules/portal/    # [todo] Amplify + Cognito + AppSync + WAF
.kiro/steering/    # IA context (product, structure, tech, terraform conventions)
```

Each `envs/<env>` configures the AWS + awscc providers (region + `default_tags`)
and wires the shared modules. Modules never reach into each other — the
environment passes one module's outputs as explicit inputs to the next. State
lives in a single S3 bucket with native locking (`use_lockfile`, no DynamoDB
table); the state key is isolated per environment
(`urbanbot/<env>/terraform.tfstate`).

## What exists today

| Module    | Status | Summary |
|-----------|--------|---------|
| `data`    | done   | CMK, S3 media (SSE-KMS + retention), DynamoDB (reports/incidents/places/users/audit-log) with streams + GSIs, SNS inbound, SQS FIFO + DLQ, EventBridge bus |
| `compute` | done   | `ingest` (SNS→deterministic guards→SQS FIFO) and `notifier` (EventBridge→WhatsApp stub) Lambdas, least-privilege IAM |
| `agent`   | done   | `create_report` / `join_incident` / `get_status` / `register_place` / `route` / `escalate` tool Lambdas, SQS `consumer`, ECR, Bedrock Guardrails, AgentCore runtime/gateway/memory (flag-gated, default off) |
| `media`   | todo   | `GetWhatsAppMessageMedia` → S3 → Step Functions → Rekognition (face/plate blur) + Transcribe + Nova |
| `portal`  | todo   | Official dashboard: Amplify (React + map), Cognito, AppSync, WAF |

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for carried-forward TODOs.

## CI / authentication

The GitLab pipeline (`.gitlab-ci.yml`) authenticates to AWS via OIDC
(`id_tokens` → `sts assume-role-with-web-identity`) — no long-lived credentials.
Stages: `tf_validate` → `tf_plan` → `tf_apply` (manual) plus manual
`tf_destroy` / `tf_untaint`.

Required CI/CD **project variables** (Settings → CI/CD → Variables):

- `AWS_ROLE_ARN` — OIDC deploy role in account `636487155766`.
- `TF_STATE_BUCKET` — existing S3 state bucket (versioning ON); injected at
  `terraform init` via `-backend-config="bucket=${TF_STATE_BUCKET}"`.

Optional overrides: `TF_ENV` (dev|qa|prod), `TF_TARGET`, `TF_DESTROY`,
`TF_UNTAINT_TARGET`.

Pushing to a `feat/*` / `fix/*` / `hotfix/*` / `release/*` branch runs
validate + plan automatically and exposes `apply` as a manual job.

## Local verification (no AWS credentials needed)

```bash
terraform fmt -check -recursive          # from repo root
cd envs/dev
terraform init -backend=false            # downloads providers, no remote backend
terraform validate
```

Do not run `terraform plan` / `apply` locally — those need account credentials
and the remote backend, which the pipeline provides via OIDC.

## Model classification accuracy

Category/severity classification accuracy must be measured on the synthetic test
set and reported here honestly (RNF-22, no inflated numbers) once the media
module lands.
