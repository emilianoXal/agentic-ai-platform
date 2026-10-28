# Contributing to urbanbot infrastructure

This repo is **Terraform-only** infrastructure for the urbanbot WhatsApp citizen
bot. Lambda application code lives next to its module in `modules/<module>/src/`.
Read this before adding or changing anything.

## Ground rules

- **Region is always `us-east-1`.** AgentCore and Rekognition don't exist in
  mx-central-1 (hackathon rule RB-03).
- **Account:** `636487155766` (aws-xaldigital-hackathon-agentic). Auth to AWS is
  via OIDC in the pipeline — there are no local credentials, and you don't need
  them to develop (validate runs with `-backend=false`).
- **Never push directly to `main`.** Work on a `feat/<topic>` branch and open a
  merge request.
- **Keep the naming convention** (below). It's baked into every resource name.

## Naming convention

Pattern: **`cdshack-urbanbot-<env>-<description>`**, kebab-case.

> **The prefix MUST be `cdshack-`.** The hackathon governance policy (the
> Terraform role's permissions boundary) only allows creating IAM roles/policies
> that start with `cdshack-` and S3 buckets containing `cdshack-`. Any other
> prefix fails `apply` with AccessDenied. The old `xaldigital-urbanbot-*` prefix
> has been migrated — do not reintroduce it.

- `<env>` is `dev`, `qa` or `prod`.
- No type prefixes on app resources (no `s3-`, `lambda-`).
- IAM roles end in `-role`, policies in `-policy`.
- Log groups: `/aws/lambda/<function-name>`.
- Inside a module, derive `local.name_prefix =
  "cdshack-urbanbot-${var.environment}"` and build every name from it.

Examples: `cdshack-urbanbot-dev-reports`,
`cdshack-urbanbot-dev-ingest.fifo`,
`cdshack-urbanbot-dev-create-report`,
`cdshack-urbanbot-dev-create-report-role`.

**State bucket exception:** the Terraform state bucket does NOT follow the
`cdshack-` prefix — it's provided by the infra team as
`s3-xaldigital-hackathon-agentic-terraform` (the governance policy was widened to
allow the `s3-xaldigital-hackathon-*` pattern). It arrives via the
`TF_STATE_BUCKET` CI/CD variable and is never hardcoded.

## Tags

Six mandatory tags, set as `default_tags` on the AWS provider in
`envs/<env>/main.tf` (NOT in modules):

```hcl
Project     = "cdshack-urbanbot"
Agente      = "urbanbot"
Environment = var.environment
ManagedBy   = "terraform"
Repo        = "hackaton-aws-cds-agentic-ai/agentic-ai-platform"
Owner       = "xaldigital"
```

The `awscc` provider does not honor `default_tags`; for awscc resources, pass
tags inline from a `local.tags` map with the same six values (see
`modules/agent/main.tf`).

## How the monorepo fits together

- `envs/<env>/` is an independent Terraform root with its own S3 state key.
- `modules/<name>/` are reusable building blocks, one per domain of the
  architecture diagram.
- **Modules never reach into each other** (`module.X.*` inside a module is
  forbidden). The environment takes module A's outputs and passes them as
  explicit inputs to module B, using the real output names 1:1.

## Adding a new module (checklist)

Example: adding `modules/media`.

1. Create `modules/media/` with:
   - `versions.tf` — `required_version >= 1.10` + `required_providers` (add
     `awscc` only if needed).
   - `variables.tf` — `environment` + the upstream module outputs you consume
     (same names, 1:1) + tunables with defaults.
   - `main.tf` — `local.name_prefix`, resources, least-privilege IAM, log
     groups, `archive_file` packaging for any Lambdas.
   - `outputs.tf` — names + ARNs a later module may need.
   - If it has Lambdas: `build/.gitkeep` and a `.gitignore` entry
     (`modules/media/build/*` + `!modules/media/build/.gitkeep`).
2. Wire it into **all three** environments. In `envs/dev/main.tf` add
   `module "media" { ... }` passing the real upstream outputs; add new vars to
   `envs/dev/variables.tf`; re-export useful outputs in `envs/dev/outputs.tf`.
   Mirror the block into `envs/qa` and `envs/prod`.
3. If you add a provider, declare it in `envs/*/versions.tf` and configure it in
   `envs/*/main.tf`.
4. Verify locally (below).
5. Commit on a `feat/<topic>` branch, push, open an MR to `main`.

## IAM: least privilege (required)

Each Lambda gets its own role + customer-managed policy. No wildcard managed
policies. Scope every statement to the exact ARN the handler touches. GSI access
needs the index ARN (`"${table_arn}/index/<index_name>"`) in addition to the
table ARN. Any role touching CMK-encrypted resources needs `kms:Decrypt` +
`kms:GenerateDataKey` on the CMK ARN.

## Lambda handlers

- Python 3.12, handler `handler.lambda_handler`, stdlib + boto3 only. Exception:
  the compute `media` blur Lambda uses the Pillow layer
  (`modules/compute/layers/pillow/`), built by the CI `media:build` job.
- Structured JSON logging with **PII masking**: never log the full phone or
  message text — use last-4 digits, a hash of the id, and the text length.
  Copy the helper from `modules/compute/src/ingest/handler.py`.
- Each `src/<fn>/` directory is self-contained (duplicate the small masking
  helper rather than sharing a layer).

## Resources needing an artifact that doesn't exist yet

If a resource needs something not built yet (e.g. a container image in ECR),
gate it behind an `enable_<thing>` bool variable (default `false`) using
`count`, and leave a documented TODO — so `terraform validate` and the dev plan
stay clean without the artifact. Pattern: the AgentCore resources in
`modules/agent/main.tf`.

## Local verification (run before every commit)

```bash
terraform fmt -recursive && terraform fmt -check -recursive
cd envs/dev && terraform init -backend=false && terraform validate
# repeat init -backend=false + validate in envs/qa and envs/prod
# compile handlers:
python3 -c "import py_compile,glob; [py_compile.compile(f, doraise=True) for f in glob.glob('modules/**/src/**/handler.py', recursive=True)]"
# ingest payload tests (EUM Social + flat simulator JSON):
python3 -m unittest discover -s modules/compute/tests
```

Then clean up `.terraform/` dirs, generated `build/*.zip`, and `__pycache__`
(keep the `.gitkeep` files). Don't commit `.terraform/`, state, zips, `.pyc`, or
the `.agents/` directory (all gitignored).

## Carried-forward TODOs

1. Push the Strands agent container image to ECR before setting
   `enable_agentcore_runtime = true`.
2. Implement `InvokeAgentRuntime` in `modules/agent/src/consumer/handler.py`
   (currently a gated no-op TODO).
3. Replace the stubbed send in `modules/compute/src/notifier/handler.py` with
   the real CDS `SendWhatsAppMessage` (socialmessaging) — required by RB-01.
4. AgentCore Gateway `CUSTOM_JWT` needs an `authorizer_configuration` with a
   real OIDC discovery URL once the IdP is chosen.
5. Build the `media` and `portal` modules.

## Spanish/English

The bot talks to users in Spanish (es-MX). Code, comments, resource names, and
contest deliverables are in English.
