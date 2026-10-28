---
inclusion: fileMatch
fileMatchPattern: "**/*.{tf,hcl}"
---

# Convenciones de Terraform y cómo agregar un módulo

## Nomenclatura de recursos AWS

Patrón: **`cdshack-urbanbot-<env>-<descripcion>`**, siempre kebab-case.

> **El prefijo DEBE ser `cdshack-`.** La política de gobierno del hackathon
> (permissions boundary del rol de Terraform) solo permite crear IAM roles y
> policies que empiecen con `cdshack-` y buckets S3 que contengan `cdshack-`.
> Cualquier otro prefijo hace fallar el `apply` con AccessDenied. No uses
> `xaldigital-urbanbot-*` (nombre viejo, ya migrado).

- `<env>` es `dev`, `qa` o `prod`.
- Dentro del módulo se deriva un local:
  `local.name_prefix = "cdshack-urbanbot-${var.environment}"`.
- **Sin prefijos de tipo** en recursos de aplicación (no `s3-`, `lambda-`,
  `role-`).
- **Con sufijos de tipo** en IAM: roles terminan en `-role`, policies en
  `-policy`.
- Log groups: `/aws/lambda/<function-name>` (o `/aws/<servicio>/<name>`).
- Sin abreviaciones ambiguas (usa `create-report`, no `cr`).

Ejemplos reales:
`cdshack-urbanbot-dev-reports` (DynamoDB),
`cdshack-urbanbot-dev-ingest.fifo` (SQS),
`cdshack-urbanbot-dev-create-report` (Lambda),
`cdshack-urbanbot-dev-create-report-role` (IAM role).

### Excepción: bucket de state de Terraform

El bucket de state NO sigue el prefijo `cdshack-`: lo provee el team de infra y
se llama `s3-xaldigital-hackathon-agentic-terraform` (patrón
`s3-xaldigital-hackathon-*`). La política de gobierno fue ampliada para permitir
ese patrón. El bucket llega por la variable de CI/CD `TF_STATE_BUCKET`, no se
hardcodea.

## Tags

Los tags van como **`default_tags` del provider en `envs/<env>/main.tf`**, NO en
los módulos. Los seis tags obligatorios:

```hcl
Project     = "cdshack-urbanbot"
Agente      = "urbanbot"
Environment = var.environment
ManagedBy   = "terraform"
Repo        = "hackaton-aws-cds-agentic-ai/agentic-ai-platform"
Owner       = "xaldigital"
```

Excepción: el provider **`awscc` NO honra `default_tags`**. Para recursos awscc
que aceptan tags, pásalos inline desde un `local.tags` con esos mismos seis
valores (ver `modules/agent/main.tf`).

## Idioms obligatorios

- `required_version >= 1.10`; providers pineados (`aws ~> 5.0`,
  `archive ~> 2.0`, `awscc ~> 1.0` si usas AgentCore).
- Usa recursos separados, NO bloques inline deprecados (ej. S3: usa
  `aws_s3_bucket_versioning`, `aws_s3_bucket_server_side_encryption_configuration`,
  etc., no los argumentos inline del `aws_s3_bucket`).
- DynamoDB: `PAY_PER_REQUEST`, `server_side_encryption` con la CMK,
  `point_in_time_recovery` on.
- `terraform fmt -check -recursive` debe pasar limpio.

## IAM — mínimo privilegio (obligatorio, RNF-06)

Cada Lambda tiene **su propio** rol + policy customer-managed (patrón
`aws_iam_role` + `aws_iam_policy` + `aws_iam_role_policy_attachment`). NO uses
managed policies con wildcards (`AWSLambdaBasicExecutionRole`): escribe los
permisos de logs explícitos acotados al ARN del log group.

Reglas:
- **Permissions boundary OBLIGATORIO.** La política de gobierno DENIEGA
  `iam:CreateRole` si el rol no se crea con el boundary
  `base-cdshack-limite-permisos`. Por eso TODO `aws_iam_role` debe llevar
  `permissions_boundary = var.permissions_boundary_arn`. El módulo declara la
  variable `permissions_boundary_arn` y el entorno la pasa (su default es
  `arn:aws:iam::636487155766:policy/base-cdshack-limite-permisos`). Un rol sin
  boundary hace fallar el `apply` con AccessDenied / explicit deny.
- Cada statement acota `resources` al ARN exacto que el handler toca.
- Acceso a un GSI requiere el ARN del índice:
  `"${table_arn}/index/<index_name>"` (ej.
  `"${var.incidents_table_arn}/index/by-geohash"`), además del ARN de la tabla.
- Todo rol que lea/escriba recursos cifrados con la CMK necesita
  `kms:Decrypt` + `kms:GenerateDataKey` sobre `var.kms_key_arn`.

## Packaging de Lambdas

- Código fuente en `modules/<modulo>/src/<funcion>/handler.py` (legible,
  commiteado).
- `data "archive_file"` zippea cada dir a `modules/<modulo>/build/<funcion>.zip`
  en tiempo de plan.
- `modules/<modulo>/build/*` va en `.gitignore` con excepción para `.gitkeep`:
  ```
  modules/<modulo>/build/*
  !modules/<modulo>/build/.gitkeep
  ```
- La Lambda usa `filename = data.archive_file.<fn>.output_path` y
  `source_code_hash = data.archive_file.<fn>.output_base64sha256`.
- Cada dir de `src/` es autocontenido (duplica el helper de ~15 líneas de
  masking/log en vez de compartir código, para que el zip por función sea
  simple).

## Cómo agregar un módulo nuevo (paso a paso)

Supón que agregas `modules/media`:

1. **Crea la carpeta del módulo** con cuatro archivos:
   - `versions.tf` — `required_version` + `required_providers` (copia de un
     módulo existente; añade `awscc` solo si lo necesitas).
   - `variables.tf` — `environment` + los outputs de otros módulos que
     consumas, con sus **nombres reales 1:1** (no renombres) + tunables con
     defaults.
   - `main.tf` — `local.name_prefix`, los recursos, IAM mínimo privilegio, log
     groups, packaging.
   - `outputs.tf` — todo lo que un módulo posterior pueda necesitar
     (names + ARNs).
   - Si tiene Lambdas: `build/.gitkeep` + entrada en `.gitignore`.
2. **No alcances otros módulos desde dentro** (`module.X.*` prohibido en un
   módulo). Declara variables y recibe los valores desde el entorno.
3. **Conéctalo en los tres entornos.** En `envs/dev/main.tf` agrega el bloque
   `module "media" { ... }` pasando los outputs reales de los módulos de los que
   depende. Añade variables nuevas a `envs/dev/variables.tf` con defaults.
   Re-exporta lo útil en `envs/dev/outputs.tf`. Luego **espeja** el bloque en
   `envs/qa/main.tf` y `envs/prod/main.tf`.
4. Si usas un provider nuevo (ej. `awscc`), agrégalo a `envs/*/versions.tf` y
   configura el provider en `envs/*/main.tf`.
5. **Verifica localmente** antes de commitear:
   ```bash
   terraform fmt -recursive && terraform fmt -check -recursive
   cd envs/dev && terraform init -backend=false && terraform validate
   # repite validate en envs/qa y envs/prod
   ```
   y `py_compile` los handlers. Limpia `.terraform/`, zips y `__pycache__`
   (deja los `.gitkeep`).
6. Commitea en una rama `feat/<tema>` y abre un merge request a `main`.

## Recursos que requieren imagen/código que aún no existe

Si un recurso necesita un artefacto que todavía no está disponible (ej. una
imagen de contenedor en ECR), **no bloquees `validate`**: pon el recurso detrás
de una variable `enable_<algo>` (bool, default `false`) usando `count`, y
documenta un TODO. Así `terraform validate` y el plan de dev quedan limpios sin
el artefacto. Patrón en `modules/agent/main.tf` (recursos AgentCore).

## Qué NO hacer

- No hardcodear el bucket de state (viene por `-backend-config`).
- No crear recursos fuera de `us-east-1`.
- No poner tags en los módulos (van en `default_tags` del entorno).
- No usar managed policies amplias para Lambdas.
- No loguear PII cruda en los handlers.
- No hacer push directo a `main`.
