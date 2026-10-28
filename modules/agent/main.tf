locals {
  name_prefix = "cdshack-urbanbot-${var.environment}"

  # awscc does NOT honour provider default_tags, so AgentCore resources that
  # accept tags set these six inline (same keys/values as the env default_tags).
  tags = {
    Project     = "cdshack-urbanbot"
    Agente      = "urbanbot"
    Environment = var.environment
    ManagedBy   = "terraform"
    Repo        = "hackaton-aws-cds-agentic-ai/agentic-ai-platform"
    Owner       = "xaldigital"
  }

  # GSI index ARNs (string-concat from the table ARN).
  incidents_geohash_index_arn = "${var.incidents_table_arn}/index/by-geohash"
  reports_user_index_arn      = "${var.reports_table_arn}/index/by-user"

  # Foundation-model + derived cross-region (US) inference-profile ARNs.
  model_arn             = "arn:aws:bedrock:us-east-1::foundation-model/${var.bedrock_model_id}"
  inference_profile_arn = "arn:aws:bedrock:us-east-1:${data.aws_caller_identity.current.account_id}:inference-profile/us.${var.bedrock_model_id}"
}

data "aws_caller_identity" "current" {}

# =============================================================================
# Packaging — archive_file zips each handler's source dir at plan time into
# build/ (gitignored except .gitkeep); the CI plan job ships build/ as an
# artifact so apply on a clean runner finds the zips.
# =============================================================================
data "archive_file" "create_report" {
  type        = "zip"
  source_dir  = "${path.module}/src/create_report"
  output_path = "${path.module}/build/create_report.zip"
}

data "archive_file" "join_incident" {
  type        = "zip"
  source_dir  = "${path.module}/src/join_incident"
  output_path = "${path.module}/build/join_incident.zip"
}

data "archive_file" "get_status" {
  type        = "zip"
  source_dir  = "${path.module}/src/get_status"
  output_path = "${path.module}/build/get_status.zip"
}

data "archive_file" "register_place" {
  type        = "zip"
  source_dir  = "${path.module}/src/register_place"
  output_path = "${path.module}/build/register_place.zip"
}

data "archive_file" "route" {
  type        = "zip"
  source_dir  = "${path.module}/src/route"
  output_path = "${path.module}/build/route.zip"
}

data "archive_file" "escalate" {
  type        = "zip"
  source_dir  = "${path.module}/src/escalate"
  output_path = "${path.module}/build/escalate.zip"
}

data "archive_file" "consumer" {
  type        = "zip"
  source_dir  = "${path.module}/src/consumer"
  output_path = "${path.module}/build/consumer.zip"
}

# =============================================================================
# CloudWatch log groups — one per Lambda; IAM scopes to a known ARN.
# =============================================================================
resource "aws_cloudwatch_log_group" "create_report" {
  name              = "/aws/lambda/${local.name_prefix}-create-report"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "join_incident" {
  name              = "/aws/lambda/${local.name_prefix}-join-incident"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "get_status" {
  name              = "/aws/lambda/${local.name_prefix}-get-status"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "register_place" {
  name              = "/aws/lambda/${local.name_prefix}-register-place"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "route" {
  name              = "/aws/lambda/${local.name_prefix}-route"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "escalate" {
  name              = "/aws/lambda/${local.name_prefix}-escalate"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "consumer" {
  name              = "/aws/lambda/${local.name_prefix}-consumer"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "agentcore" {
  name              = "/aws/bedrock-agentcore/${local.name_prefix}-agent"
  retention_in_days = var.log_retention_days
}

# =============================================================================
# Shared Lambda assume-role policy (trust: lambda.amazonaws.com).
# =============================================================================
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# =============================================================================
# create_report — role + least-privilege policy + attachment.
# reports R/W + incidents R/W + by-geohash GSI query + audit-log + kms + logs.
# =============================================================================
resource "aws_iam_role" "create_report" {
  name                 = "${local.name_prefix}-create-report-role"
  assume_role_policy   = data.aws_iam_policy_document.lambda_assume.json
  permissions_boundary = var.permissions_boundary_arn
}

data "aws_iam_policy_document" "create_report" {
  statement {
    sid    = "Logs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      aws_cloudwatch_log_group.create_report.arn,
      "${aws_cloudwatch_log_group.create_report.arn}:*",
    ]
  }

  statement {
    sid       = "ReportsWrite"
    effect    = "Allow"
    actions   = ["dynamodb:PutItem", "dynamodb:UpdateItem"]
    resources = [var.reports_table_arn]
  }

  statement {
    sid    = "IncidentsReadWrite"
    effect = "Allow"
    actions = [
      "dynamodb:Query",
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
    ]
    resources = [
      var.incidents_table_arn,
      local.incidents_geohash_index_arn,
    ]
  }

  statement {
    sid       = "AuditWrite"
    effect    = "Allow"
    actions   = ["dynamodb:PutItem"]
    resources = [var.audit_log_table_arn]
  }

  statement {
    sid       = "KmsDataKey"
    effect    = "Allow"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_policy" "create_report" {
  name   = "${local.name_prefix}-create-report-policy"
  policy = data.aws_iam_policy_document.create_report.json
}

resource "aws_iam_role_policy_attachment" "create_report" {
  role       = aws_iam_role.create_report.name
  policy_arn = aws_iam_policy.create_report.arn
}

# =============================================================================
# join_incident — role + policy + attachment.
# incidents R/W + reports write (create-then-join) + audit-log + kms + logs.
# =============================================================================
resource "aws_iam_role" "join_incident" {
  name                 = "${local.name_prefix}-join-incident-role"
  assume_role_policy   = data.aws_iam_policy_document.lambda_assume.json
  permissions_boundary = var.permissions_boundary_arn
}

data "aws_iam_policy_document" "join_incident" {
  statement {
    sid    = "Logs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      aws_cloudwatch_log_group.join_incident.arn,
      "${aws_cloudwatch_log_group.join_incident.arn}:*",
    ]
  }

  statement {
    sid       = "IncidentsUpdate"
    effect    = "Allow"
    actions   = ["dynamodb:UpdateItem"]
    resources = [var.incidents_table_arn]
  }

  statement {
    sid       = "ReportsWrite"
    effect    = "Allow"
    actions   = ["dynamodb:PutItem"]
    resources = [var.reports_table_arn]
  }

  statement {
    sid       = "AuditWrite"
    effect    = "Allow"
    actions   = ["dynamodb:PutItem"]
    resources = [var.audit_log_table_arn]
  }

  statement {
    sid       = "KmsDataKey"
    effect    = "Allow"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_policy" "join_incident" {
  name   = "${local.name_prefix}-join-incident-policy"
  policy = data.aws_iam_policy_document.join_incident.json
}

resource "aws_iam_role_policy_attachment" "join_incident" {
  role       = aws_iam_role.join_incident.name
  policy_arn = aws_iam_policy.join_incident.arn
}

# =============================================================================
# get_status — role + policy + attachment (read-only).
# reports read + by-user GSI + incidents read + kms + logs.
# =============================================================================
resource "aws_iam_role" "get_status" {
  name                 = "${local.name_prefix}-get-status-role"
  assume_role_policy   = data.aws_iam_policy_document.lambda_assume.json
  permissions_boundary = var.permissions_boundary_arn
}

data "aws_iam_policy_document" "get_status" {
  statement {
    sid    = "Logs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      aws_cloudwatch_log_group.get_status.arn,
      "${aws_cloudwatch_log_group.get_status.arn}:*",
    ]
  }

  statement {
    sid     = "ReportsRead"
    effect  = "Allow"
    actions = ["dynamodb:GetItem", "dynamodb:Query"]
    resources = [
      var.reports_table_arn,
      local.reports_user_index_arn,
    ]
  }

  statement {
    sid       = "IncidentsRead"
    effect    = "Allow"
    actions   = ["dynamodb:GetItem"]
    resources = [var.incidents_table_arn]
  }

  statement {
    sid       = "KmsDataKey"
    effect    = "Allow"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_policy" "get_status" {
  name   = "${local.name_prefix}-get-status-policy"
  policy = data.aws_iam_policy_document.get_status.json
}

resource "aws_iam_role_policy_attachment" "get_status" {
  role       = aws_iam_role.get_status.name
  policy_arn = aws_iam_policy.get_status.arn
}

# =============================================================================
# register_place — role + policy + attachment.
# places R/W + Query (table hash key, no GSI) + users read + audit + kms + logs.
# =============================================================================
resource "aws_iam_role" "register_place" {
  name                 = "${local.name_prefix}-register-place-role"
  assume_role_policy   = data.aws_iam_policy_document.lambda_assume.json
  permissions_boundary = var.permissions_boundary_arn
}

data "aws_iam_policy_document" "register_place" {
  statement {
    sid    = "Logs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      aws_cloudwatch_log_group.register_place.arn,
      "${aws_cloudwatch_log_group.register_place.arn}:*",
    ]
  }

  statement {
    sid       = "PlacesReadWrite"
    effect    = "Allow"
    actions   = ["dynamodb:Query", "dynamodb:PutItem", "dynamodb:GetItem"]
    resources = [var.places_table_arn]
  }

  statement {
    sid       = "UsersRead"
    effect    = "Allow"
    actions   = ["dynamodb:GetItem"]
    resources = [var.users_table_arn]
  }

  statement {
    sid       = "AuditWrite"
    effect    = "Allow"
    actions   = ["dynamodb:PutItem"]
    resources = [var.audit_log_table_arn]
  }

  statement {
    sid       = "KmsDataKey"
    effect    = "Allow"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_policy" "register_place" {
  name   = "${local.name_prefix}-register-place-policy"
  policy = data.aws_iam_policy_document.register_place.json
}

resource "aws_iam_role_policy_attachment" "register_place" {
  role       = aws_iam_role.register_place.name
  policy_arn = aws_iam_policy.register_place.arn
}

# =============================================================================
# route — role + policy + attachment.
# incidents R/W + events:PutEvents on the bus + audit + kms + logs.
# =============================================================================
resource "aws_iam_role" "route" {
  name                 = "${local.name_prefix}-route-role"
  assume_role_policy   = data.aws_iam_policy_document.lambda_assume.json
  permissions_boundary = var.permissions_boundary_arn
}

data "aws_iam_policy_document" "route" {
  statement {
    sid    = "Logs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      aws_cloudwatch_log_group.route.arn,
      "${aws_cloudwatch_log_group.route.arn}:*",
    ]
  }

  statement {
    sid       = "IncidentsReadWrite"
    effect    = "Allow"
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [var.incidents_table_arn]
  }

  statement {
    sid       = "EventsPut"
    effect    = "Allow"
    actions   = ["events:PutEvents"]
    resources = [var.events_bus_arn]
  }

  statement {
    sid       = "AuditWrite"
    effect    = "Allow"
    actions   = ["dynamodb:PutItem"]
    resources = [var.audit_log_table_arn]
  }

  statement {
    sid       = "KmsDataKey"
    effect    = "Allow"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_policy" "route" {
  name   = "${local.name_prefix}-route-policy"
  policy = data.aws_iam_policy_document.route.json
}

resource "aws_iam_role_policy_attachment" "route" {
  role       = aws_iam_role.route.name
  policy_arn = aws_iam_policy.route.arn
}

# =============================================================================
# escalate — role + policy + attachment.
# incidents R/W + events:PutEvents on the bus + audit + kms + logs.
# =============================================================================
resource "aws_iam_role" "escalate" {
  name                 = "${local.name_prefix}-escalate-role"
  assume_role_policy   = data.aws_iam_policy_document.lambda_assume.json
  permissions_boundary = var.permissions_boundary_arn
}

data "aws_iam_policy_document" "escalate" {
  statement {
    sid    = "Logs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      aws_cloudwatch_log_group.escalate.arn,
      "${aws_cloudwatch_log_group.escalate.arn}:*",
    ]
  }

  statement {
    sid       = "IncidentsReadWrite"
    effect    = "Allow"
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [var.incidents_table_arn]
  }

  statement {
    sid       = "EventsPut"
    effect    = "Allow"
    actions   = ["events:PutEvents"]
    resources = [var.events_bus_arn]
  }

  statement {
    sid       = "AuditWrite"
    effect    = "Allow"
    actions   = ["dynamodb:PutItem"]
    resources = [var.audit_log_table_arn]
  }

  statement {
    sid       = "KmsDataKey"
    effect    = "Allow"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_policy" "escalate" {
  name   = "${local.name_prefix}-escalate-policy"
  policy = data.aws_iam_policy_document.escalate.json
}

resource "aws_iam_role_policy_attachment" "escalate" {
  role       = aws_iam_role.escalate.name
  policy_arn = aws_iam_policy.escalate.arn
}

# =============================================================================
# consumer — role + policy + attachment.
# sqs receive/delete on the ingest queue + dynamodb write (audit) + kms + logs.
# bedrock-agentcore:InvokeAgentRuntime left as a TODO (runtime flag false).
# =============================================================================
resource "aws_iam_role" "consumer" {
  name                 = "${local.name_prefix}-consumer-role"
  assume_role_policy   = data.aws_iam_policy_document.lambda_assume.json
  permissions_boundary = var.permissions_boundary_arn
}

data "aws_iam_policy_document" "consumer" {
  statement {
    sid    = "Logs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      aws_cloudwatch_log_group.consumer.arn,
      "${aws_cloudwatch_log_group.consumer.arn}:*",
    ]
  }

  statement {
    sid    = "SqsConsume"
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
    ]
    resources = [var.ingest_queue_arn]
  }

  statement {
    sid       = "AuditWrite"
    effect    = "Allow"
    actions   = ["dynamodb:PutItem"]
    resources = [var.audit_log_table_arn]
  }

  statement {
    sid       = "KmsDataKey"
    effect    = "Allow"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [var.kms_key_arn]
  }

  # TODO(agentcore): when enable_agentcore_runtime is true, grant
  # "bedrock-agentcore:InvokeAgentRuntime" on the runtime ARN so the consumer
  # can hand off to the AgentCore runtime.
}

resource "aws_iam_policy" "consumer" {
  name   = "${local.name_prefix}-consumer-policy"
  policy = data.aws_iam_policy_document.consumer.json
}

resource "aws_iam_role_policy_attachment" "consumer" {
  role       = aws_iam_role.consumer.name
  policy_arn = aws_iam_policy.consumer.arn
}

# =============================================================================
# Lambda functions.
# =============================================================================
resource "aws_lambda_function" "create_report" {
  function_name    = "${local.name_prefix}-create-report"
  role             = aws_iam_role.create_report.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.create_report.output_path
  source_code_hash = data.archive_file.create_report.output_base64sha256
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      REPORTS_TABLE           = var.reports_table_name
      INCIDENTS_TABLE         = var.incidents_table_name
      INCIDENTS_GEOHASH_INDEX = "by-geohash"
      AUDIT_TABLE             = var.audit_log_table_name
      RECENT_WINDOW_HOURS     = tostring(var.recent_window_hours)
      LOG_LEVEL               = var.log_level
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.create_report,
    aws_iam_role_policy_attachment.create_report,
  ]
}

resource "aws_lambda_function" "join_incident" {
  function_name    = "${local.name_prefix}-join-incident"
  role             = aws_iam_role.join_incident.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.join_incident.output_path
  source_code_hash = data.archive_file.join_incident.output_base64sha256
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      INCIDENTS_TABLE = var.incidents_table_name
      REPORTS_TABLE   = var.reports_table_name
      AUDIT_TABLE     = var.audit_log_table_name
      LOG_LEVEL       = var.log_level
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.join_incident,
    aws_iam_role_policy_attachment.join_incident,
  ]
}

resource "aws_lambda_function" "get_status" {
  function_name    = "${local.name_prefix}-get-status"
  role             = aws_iam_role.get_status.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.get_status.output_path
  source_code_hash = data.archive_file.get_status.output_base64sha256
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      REPORTS_TABLE      = var.reports_table_name
      REPORTS_USER_INDEX = "by-user"
      INCIDENTS_TABLE    = var.incidents_table_name
      LOG_LEVEL          = var.log_level
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.get_status,
    aws_iam_role_policy_attachment.get_status,
  ]
}

resource "aws_lambda_function" "register_place" {
  function_name    = "${local.name_prefix}-register-place"
  role             = aws_iam_role.register_place.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.register_place.output_path
  source_code_hash = data.archive_file.register_place.output_base64sha256
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      PLACES_TABLE           = var.places_table_name
      USERS_TABLE            = var.users_table_name
      AUDIT_TABLE            = var.audit_log_table_name
      MAX_PLACES_PER_USER    = tostring(var.max_places_per_user)
      DEFAULT_PLACE_RADIUS_M = tostring(var.default_place_radius_m)
      LOG_LEVEL              = var.log_level
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.register_place,
    aws_iam_role_policy_attachment.register_place,
  ]
}

resource "aws_lambda_function" "route" {
  function_name    = "${local.name_prefix}-route"
  role             = aws_iam_role.route.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.route.output_path
  source_code_hash = data.archive_file.route.output_base64sha256
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      ROUTING_RULES_JSON = var.routing_rules_json
      INCIDENTS_TABLE    = var.incidents_table_name
      EVENTS_BUS_NAME    = var.events_bus_name
      AUDIT_TABLE        = var.audit_log_table_name
      LOG_LEVEL          = var.log_level
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.route,
    aws_iam_role_policy_attachment.route,
  ]
}

resource "aws_lambda_function" "escalate" {
  function_name    = "${local.name_prefix}-escalate"
  role             = aws_iam_role.escalate.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.escalate.output_path
  source_code_hash = data.archive_file.escalate.output_base64sha256
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      INCIDENTS_TABLE           = var.incidents_table_name
      EVENTS_BUS_NAME           = var.events_bus_name
      AUDIT_TABLE               = var.audit_log_table_name
      ESCALATE_REPORT_THRESHOLD = tostring(var.escalate_report_threshold)
      ESCALATE_DAYS_THRESHOLD   = tostring(var.escalate_days_threshold)
      LOG_LEVEL                 = var.log_level
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.escalate,
    aws_iam_role_policy_attachment.escalate,
  ]
}

resource "aws_lambda_function" "consumer" {
  function_name    = "${local.name_prefix}-consumer"
  role             = aws_iam_role.consumer.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.consumer.output_path
  source_code_hash = data.archive_file.consumer.output_base64sha256
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      AUDIT_TABLE               = var.audit_log_table_name
      AGENTCORE_RUNTIME_ENABLED = tostring(var.enable_agentcore_runtime)
      AGENTCORE_RUNTIME_ARN     = var.enable_agentcore_runtime ? one(awscc_bedrockagentcore_runtime.this[*].agent_runtime_arn) : ""
      LOG_LEVEL                 = var.log_level
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.consumer,
    aws_iam_role_policy_attachment.consumer,
  ]
}

# =============================================================================
# SQS event-source mapping — FIFO ingest queue -> consumer. Partial-batch
# failures reported via ReportBatchItemFailures so poison records ride the
# existing ingest-queue redrive (maxReceiveCount = 5 -> ingest_dlq) to the DLQ.
# =============================================================================
resource "aws_lambda_event_source_mapping" "consumer" {
  event_source_arn        = var.ingest_queue_arn
  function_name           = aws_lambda_function.consumer.function_name
  batch_size              = 5
  enabled                 = true
  function_response_types = ["ReportBatchItemFailures"]
}

# =============================================================================
# Bedrock Guardrail — minimal-but-valid: prompt-injection content filter +
# DENY topics for disallowed WhatsApp-policy subjects (no datos financieros /
# CURP / INE), es-MX blocked input/output messages (RNF-13/14).
# =============================================================================
resource "aws_bedrock_guardrail" "this" {
  name                      = "${local.name_prefix}-agent-guardrail"
  description               = "Guardrail del agente urbanbot: bloquea prompt-injection y temas no permitidos por politica de WhatsApp."
  blocked_input_messaging   = "No puedo ayudarte con esa solicitud."
  blocked_outputs_messaging = "No puedo compartir esa informacion."

  content_policy_config {
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE"
    }
    filters_config {
      type            = "INSULTS"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
  }

  topic_policy_config {
    topics_config {
      name       = "datos_financieros"
      type       = "DENY"
      definition = "Solicitudes o manejo de datos financieros sensibles como numeros de tarjeta, cuentas bancarias o pagos."
      examples   = ["Dame mi numero de tarjeta", "Transfiere dinero a esta cuenta"]
    }
    topics_config {
      name       = "identificacion_oficial"
      type       = "DENY"
      definition = "Solicitudes o manejo de identificadores oficiales como CURP, INE o RFC."
      examples   = ["Cual es mi CURP", "Dame los datos de mi INE"]
    }
  }
}

resource "aws_bedrock_guardrail_version" "this" {
  guardrail_arn = aws_bedrock_guardrail.this.guardrail_arn
  description   = "Version publicada del guardrail de urbanbot."
  skip_destroy  = true
}

# =============================================================================
# ECR repository — created unconditionally so a build pipeline can push the
# Strands agent image before the AgentCore runtime flag is turned on.
# =============================================================================
resource "aws_ecr_repository" "agent" {
  name                 = "${local.name_prefix}-agent"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = var.kms_key_arn
  }
}

# =============================================================================
# AgentCore execution role — created REGARDLESS of the flags so its ARN is a
# stable output. Trust principal verified against the awscc runtime example:
# bedrock-agentcore.amazonaws.com.
# =============================================================================
data "aws_iam_policy_document" "agentcore_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "agentcore_exec" {
  name                 = "${local.name_prefix}-agentcore-exec-role"
  assume_role_policy   = data.aws_iam_policy_document.agentcore_assume.json
  permissions_boundary = var.permissions_boundary_arn
}

data "aws_iam_policy_document" "agentcore_exec" {
  statement {
    sid    = "BedrockInvoke"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = [
      local.model_arn,
      local.inference_profile_arn,
    ]
  }

  statement {
    sid       = "GuardrailApply"
    effect    = "Allow"
    actions   = ["bedrock:ApplyGuardrail"]
    resources = [aws_bedrock_guardrail.this.guardrail_arn]
  }

  statement {
    sid    = "EcrPull"
    effect = "Allow"
    actions = [
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
      "ecr:BatchCheckLayerAvailability",
    ]
    resources = [aws_ecr_repository.agent.arn]
  }

  statement {
    sid       = "EcrAuthToken"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid     = "InvokeTools"
    effect  = "Allow"
    actions = ["lambda:InvokeFunction"]
    resources = [
      aws_lambda_function.create_report.arn,
      aws_lambda_function.join_incident.arn,
      aws_lambda_function.get_status.arn,
      aws_lambda_function.register_place.arn,
      aws_lambda_function.route.arn,
      aws_lambda_function.escalate.arn,
    ]
  }

  statement {
    sid    = "Logs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      aws_cloudwatch_log_group.agentcore.arn,
      "${aws_cloudwatch_log_group.agentcore.arn}:*",
    ]
  }

  statement {
    sid       = "KmsDataKey"
    effect    = "Allow"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_policy" "agentcore_exec" {
  name   = "${local.name_prefix}-agentcore-exec-policy"
  policy = data.aws_iam_policy_document.agentcore_exec.json
}

resource "aws_iam_role_policy_attachment" "agentcore_exec" {
  role       = aws_iam_role.agentcore_exec.name
  policy_arn = aws_iam_policy.agentcore_exec.arn
}

# =============================================================================
# AgentCore resources (awscc) — flag-gated via count, default false. With the
# flags false (count = 0) terraform validate / a dev plan contain ZERO
# AgentCore resources and need no agent image. awscc does NOT honour provider
# default_tags, so tags are set inline from local.tags.
#
# Resource type names + required args VERIFIED against the hashicorp/awscc
# provider docs (bedrockagentcore_runtime / _gateway / _memory).
# =============================================================================
resource "awscc_bedrockagentcore_runtime" "this" {
  count = var.enable_agentcore_runtime ? 1 : 0

  agent_runtime_name = replace("${local.name_prefix}-agent", "-", "_")
  role_arn           = aws_iam_role.agentcore_exec.arn

  agent_runtime_artifact = {
    container_configuration = {
      # TODO(agentcore): :latest is a placeholder — the Strands agent image must
      # be pushed to this ECR repo before enabling enable_agentcore_runtime.
      container_uri = "${aws_ecr_repository.agent.repository_url}:latest"
    }
  }

  network_configuration = {
    network_mode = "PUBLIC"
  }

  environment_variables = {
    LOG_LEVEL = var.log_level
  }

  tags = local.tags
}

resource "awscc_bedrockagentcore_gateway" "this" {
  count = var.enable_agentcore_gateway ? 1 : 0

  name     = replace("${local.name_prefix}-gateway", "-", "_")
  role_arn = aws_iam_role.agentcore_exec.arn
  # TODO(agentcore): CUSTOM_JWT requires authorizer_configuration with a real
  # OIDC discovery_url; wire it when the identity provider is chosen.
  authorizer_type = "CUSTOM_JWT"

  tags = local.tags
}

resource "awscc_bedrockagentcore_memory" "this" {
  count = var.enable_agentcore_memory ? 1 : 0

  name                  = replace("${local.name_prefix}-memory", "-", "_")
  event_expiry_duration = 30

  tags = local.tags
}
