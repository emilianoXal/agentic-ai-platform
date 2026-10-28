---
inclusion: always
---

# Stack técnico y operación

## Cuenta y región

- **Cuenta AWS:** `636487155766` (aws-xaldigital-hackathon-agentic).
- **Región:** `us-east-1` SIEMPRE (RB-03: AgentCore y Rekognition no existen en
  mx-central-1). No crees recursos en otra región.

## Terraform

- Versión pineada: **1.10** (`.terraform-version`). `required_version >= 1.10`.
- Providers:
  - `hashicorp/aws ~> 5.0` — mayoría de recursos.
  - `hashicorp/archive ~> 2.0` — zip del código Lambda (`archive_file`).
  - `hashicorp/awscc ~> 1.0` — recursos de AgentCore
    (`awscc_bedrockagentcore_runtime` / `_gateway` / `_memory`), porque el
    provider `aws` aún no los cubre todos.
- **Backend:** S3 con **native locking** (`use_lockfile = true`, sin tabla
  DynamoDB). El bucket NO se hardcodea: se pasa en `init` vía
  `-backend-config="bucket=${TF_STATE_BUCKET}"`. State aislado por entorno con
  keys `urbanbot/<env>/terraform.tfstate`.

## Runtime de las Lambdas

- **Python 3.12**, handler `handler.lambda_handler`.
- Solo stdlib + boto3 (bundled en el runtime). No añadas dependencias externas
  sin empaquetarlas.
- Logging estructurado JSON con **PII enmascarada**: nunca loguees el teléfono
  completo ni el texto del mensaje; usa últimos 4 dígitos, hash de id, y longitud
  del texto. Reutiliza el patrón de `modules/compute/src/ingest/handler.py`.

## Pipeline CI/CD (`.gitlab-ci.yml`)

Autenticación por **OIDC** (GitLab `id_tokens` → STS `AssumeRoleWithWebIdentity`),
sin llaves estáticas. Stages:

- `tf_validate` — `terraform fmt -check -recursive` + `terraform validate`.
- `tf_plan` — `terraform plan -out=tfplan` (soporta `TF_TARGET`). Sube `tfplan`
  y `modules/compute/build/` como artifacts.
- `tf_apply` — `terraform apply tfplan` (**manual**, solo en `main`).
- `tf_destroy` — manual, gated en `TF_DESTROY=true` (solo `main`).
- `tf_untaint` — manual, gated en `TF_UNTAINT_TARGET`.
- `bedrock:smoke` — manual, solo en `main`. Invoca el inference profile Sonnet
  del agente (`us.anthropic.claude-3-5-sonnet-...`) con `bedrock-runtime converse`
  y verifica que Bedrock responde con texto (T-0011, comprobar invocación
  Bedrock). Si se cambia el modelo del agente, actualizar `BEDROCK_PROFILE_ID`
  en el job. OJO: la política de gobierno solo permite perfiles `us.*` de
  `claude-sonnet-*` y `amazon.nova-*` — no Haiku ni prefijo `global.*`.

### Variables de CI/CD requeridas (Settings → CI/CD → Variables)

- `AWS_ROLE_ARN` — rol OIDC de despliegue en la cuenta 636487155766.
- `TF_STATE_BUCKET` — bucket S3 del state (ya existe, versioning ON).

### Variables opcionales de override

- `TF_ENV` — `dev` (default) | `qa` | `prod`.
- `TF_TARGET` — lista separada por comas de recursos para `-target` en el plan.
- `TF_DESTROY` — `"true"` habilita el job de destroy.
- `TF_UNTAINT_TARGET` — dirección de recurso para des-taintear.

## Comandos locales útiles

Sin credenciales locales de la cuenta (la auth real es por OIDC en el pipeline),
así que local se valida SIN backend:

```bash
# formato (desde la raíz del repo)
terraform fmt -recursive
terraform fmt -check -recursive

# validar un entorno sin backend remoto (descarga providers)
cd envs/dev
terraform init -backend=false
terraform validate

# compilar los handlers
python3 -c "import py_compile,glob; [py_compile.compile(f, doraise=True) for f in glob.glob('modules/**/src/**/handler.py', recursive=True)]"
```

**No** corras `terraform plan`/`apply` en local (necesitan credenciales de la
cuenta y el backend). Eso lo hace el pipeline.

## Modelo Bedrock

Default: `anthropic.claude-3-5-sonnet-20241022-v2:0` (id de foundation-model
"pelado", NO el inference-profile `us.*`). El rol de ejecución deriva el ARN del
inference-profile a partir de ese id. Se puede sobreescribir con la variable
`bedrock_model_id`.
