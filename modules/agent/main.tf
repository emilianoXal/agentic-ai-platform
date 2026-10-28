locals {
  name_prefix = "cdshack-urbanbot-${var.environment}"

  # One SQS delivery must drive exactly one agent turn at a time: the consumer
  # waits past the agent timeout, the whole batch fits in the consumer timeout,
  # and the message stays invisible for six consumer timeouts.
  agent_timeout_seconds             = 90
  agent_invoke_read_timeout_seconds = 110
  consumer_timeout_seconds          = 120
  consumer_batch_size               = 1

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

data "archive_file" "delete_my_data" {
  type        = "zip"
  source_dir  = "${path.module}/src/delete_my_data"
  output_path = "${path.module}/build/delete_my_data.zip"
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

data "archive_file" "agent" {
  type        = "zip"
  source_dir  = "${path.module}/src/agent"
  output_path = "${path.module}/build/agent.zip"
}

# Strands Lambda layer — archive_file zips the committed layers/strands tree
# (requirements.txt + build.sh + the prebuilt python/ site-packages). The CI
# terraform image has no python/pip, so build.sh is run once locally and the
# resulting python/ tree is committed; archive_file only zips what exists.
data "archive_file" "strands_layer" {
  type        = "zip"
  source_dir  = "${path.module}/layers/strands"
  output_path = "${path.module}/build/strands-layer.zip"
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

resource "aws_cloudwatch_log_group" "delete_my_data" {
  name              = "/aws/lambda/${local.name_prefix}-delete-my-data"
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

resource "aws_cloudwatch_log_group" "agent" {
  name              = "/aws/lambda/${local.name_prefix}-agent"
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
  name               = "${local.name_prefix}-create-report-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
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
  name               = "${local.name_prefix}-join-incident-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
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
  name               = "${local.name_prefix}-get-status-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
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
  name               = "${local.name_prefix}-register-place-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
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

resource "aws_iam_role" "delete_my_data" {
  name               = "${local.name_prefix}-delete-my-data-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "delete_my_data" {
  statement {
    sid    = "Logs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      aws_cloudwatch_log_group.delete_my_data.arn,
      "${aws_cloudwatch_log_group.delete_my_data.arn}:*",
    ]
  }

  statement {
    sid       = "UsersDelete"
    effect    = "Allow"
    actions   = ["dynamodb:DeleteItem"]
    resources = [var.users_table_arn]
  }

  statement {
    sid       = "PlacesReadDelete"
    effect    = "Allow"
    actions   = ["dynamodb:Query", "dynamodb:DeleteItem"]
    resources = [var.places_table_arn]
  }

  statement {
    sid     = "ReportsReadAnonymize"
    effect  = "Allow"
    actions = ["dynamodb:Query", "dynamodb:UpdateItem"]
    resources = [
      var.reports_table_arn,
      local.reports_user_index_arn,
    ]
  }

  statement {
    sid       = "IncidentsUnsubscribe"
    effect    = "Allow"
    actions   = ["dynamodb:Scan", "dynamodb:UpdateItem"]
    resources = [var.incidents_table_arn]
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

  dynamic "statement" {
    for_each = var.enable_agentcore_memory ? [1] : []

    content {
      sid    = "AgentCoreMemoryErase"
      effect = "Allow"
      actions = [
        "bedrock-agentcore:ListEvents",
        "bedrock-agentcore:DeleteEvent",
        "bedrock-agentcore:ListMemoryRecords",
        "bedrock-agentcore:BatchDeleteMemoryRecords",
      ]
      resources = [one(awscc_bedrockagentcore_memory.this[*].memory_arn)]
    }
  }

  dynamic "statement" {
    for_each = var.enable_agentcore_memory ? [1] : []

    content {
      sid       = "AgentCoreMemoryIdentityKey"
      effect    = "Allow"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = [one(aws_secretsmanager_secret.agentcore_identity[*].arn)]
    }
  }
}

resource "aws_iam_policy" "delete_my_data" {
  name   = "${local.name_prefix}-delete-my-data-policy"
  policy = data.aws_iam_policy_document.delete_my_data.json
}

resource "aws_iam_role_policy_attachment" "delete_my_data" {
  role       = aws_iam_role.delete_my_data.name
  policy_arn = aws_iam_policy.delete_my_data.arn
}

# =============================================================================
# route — role + policy + attachment.
# incidents R/W + events:PutEvents on the bus + audit + kms + logs.
# =============================================================================
resource "aws_iam_role" "route" {
  name               = "${local.name_prefix}-route-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
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
  name               = "${local.name_prefix}-escalate-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
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
# sqs receive/delete on the ingest queue + dynamodb write (audit) + kms + logs
# + lambda:InvokeFunction on the agent Lambda (synchronous hand-off).
# =============================================================================
resource "aws_iam_role" "consumer" {
  name               = "${local.name_prefix}-consumer-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
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

  statement {
    sid       = "InvokeAgent"
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.agent.arn]
  }

  statement {
    sid       = "InvokeOutbound"
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = [var.outbound_function_arn]
  }
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
# Strands Lambda layer — published from the committed layers/strands tree.
# =============================================================================
resource "aws_lambda_layer_version" "strands" {
  layer_name          = "${local.name_prefix}-strands"
  filename            = data.archive_file.strands_layer.output_path
  source_code_hash    = data.archive_file.strands_layer.output_base64sha256
  compatible_runtimes = ["python3.12"]
}

# =============================================================================
# agent — role + least-privilege policy + attachment.
# Runs the Strands agent loop: Bedrock invoke + guardrail + tool-Lambda invoke
# + kms + logs. NO DynamoDB (the tool Lambdas own all table access).
# =============================================================================
resource "aws_iam_role" "agent" {
  name               = "${local.name_prefix}-agent-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "agent" {
  statement {
    sid    = "Logs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      aws_cloudwatch_log_group.agent.arn,
      "${aws_cloudwatch_log_group.agent.arn}:*",
    ]
  }

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
    sid    = "BedrockInvokeInProfileRegions"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = ["arn:aws:bedrock:*::foundation-model/${var.bedrock_model_id}"]

    condition {
      test     = "ArnEquals"
      variable = "bedrock:InferenceProfileArn"
      values   = [local.inference_profile_arn]
    }
  }

  statement {
    sid       = "GuardrailApply"
    effect    = "Allow"
    actions   = ["bedrock:ApplyGuardrail"]
    resources = [aws_bedrock_guardrail.this.guardrail_arn]
  }

  dynamic "statement" {
    for_each = var.enable_agentcore_memory ? [1] : []

    content {
      sid    = "AgentCoreMemorySession"
      effect = "Allow"
      actions = [
        "bedrock-agentcore:CreateEvent",
        "bedrock-agentcore:DeleteEvent",
        "bedrock-agentcore:GetEvent",
        "bedrock-agentcore:ListEvents",
      ]
      resources = [one(awscc_bedrockagentcore_memory.this[*].memory_arn)]
    }
  }

  dynamic "statement" {
    for_each = var.enable_agentcore_memory ? [1] : []

    content {
      sid       = "AgentCoreMemoryIdentityKey"
      effect    = "Allow"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = [one(aws_secretsmanager_secret.agentcore_identity[*].arn)]
    }
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
      aws_lambda_function.delete_my_data.arn,
    ]
  }

  statement {
    sid       = "KmsDataKey"
    effect    = "Allow"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_policy" "agent" {
  name   = "${local.name_prefix}-agent-policy"
  policy = data.aws_iam_policy_document.agent.json
}

resource "aws_iam_role_policy_attachment" "agent" {
  role       = aws_iam_role.agent.name
  policy_arn = aws_iam_policy.agent.arn
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

resource "aws_lambda_function" "delete_my_data" {
  function_name    = "${local.name_prefix}-delete-my-data"
  role             = aws_iam_role.delete_my_data.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.delete_my_data.output_path
  source_code_hash = data.archive_file.delete_my_data.output_base64sha256
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      USERS_TABLE                   = var.users_table_name
      PLACES_TABLE                  = var.places_table_name
      REPORTS_TABLE                 = var.reports_table_name
      REPORTS_USER_INDEX            = "by-user"
      INCIDENTS_TABLE               = var.incidents_table_name
      AUDIT_TABLE                   = var.audit_log_table_name
      LOG_LEVEL                     = var.log_level
      AGENTCORE_MEMORY_ID           = var.enable_agentcore_memory ? one(awscc_bedrockagentcore_memory.this[*].memory_id) : ""
      AGENTCORE_IDENTITY_SECRET_ARN = var.enable_agentcore_memory ? one(aws_secretsmanager_secret.agentcore_identity[*].arn) : ""
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.delete_my_data,
    aws_iam_role_policy_attachment.delete_my_data,
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
  timeout          = local.consumer_timeout_seconds
  memory_size      = 256

  environment {
    variables = {
      AUDIT_TABLE               = var.audit_log_table_name
      AGENT_FUNCTION_NAME       = aws_lambda_function.agent.function_name
      AGENT_INVOKE_READ_TIMEOUT = local.agent_invoke_read_timeout_seconds
      OUTBOUND_FUNCTION_NAME    = var.outbound_function_name
      LOG_LEVEL                 = var.log_level
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.consumer,
    aws_iam_role_policy_attachment.consumer,
  ]
}

resource "aws_lambda_function" "agent" {
  function_name    = "${local.name_prefix}-agent"
  role             = aws_iam_role.agent.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.agent.output_path
  source_code_hash = data.archive_file.agent.output_base64sha256
  timeout          = local.agent_timeout_seconds
  memory_size      = 1024
  layers           = [aws_lambda_layer_version.strands.arn]

  environment {
    variables = {
      BEDROCK_MODEL_ID              = var.bedrock_model_id
      GUARDRAIL_ID                  = aws_bedrock_guardrail.this.guardrail_id
      GUARDRAIL_VERSION             = aws_bedrock_guardrail_version.this.version
      TOOL_CREATE_REPORT_FN         = aws_lambda_function.create_report.function_name
      TOOL_JOIN_INCIDENT_FN         = aws_lambda_function.join_incident.function_name
      TOOL_GET_STATUS_FN            = aws_lambda_function.get_status.function_name
      TOOL_REGISTER_PLACE_FN        = aws_lambda_function.register_place.function_name
      TOOL_ROUTE_FN                 = aws_lambda_function.route.function_name
      TOOL_ESCALATE_FN              = aws_lambda_function.escalate.function_name
      TOOL_DELETE_MY_DATA_FN        = aws_lambda_function.delete_my_data.function_name
      AGENTCORE_MEMORY_ID           = var.enable_agentcore_memory ? one(awscc_bedrockagentcore_memory.this[*].memory_id) : ""
      AGENTCORE_IDENTITY_SECRET_ARN = var.enable_agentcore_memory ? one(aws_secretsmanager_secret.agentcore_identity[*].arn) : ""
      LOG_LEVEL                     = var.log_level
      SIMULATE_WHATSAPP_REPLY       = "1"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.agent,
    aws_iam_role_policy_attachment.agent,
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
  batch_size              = local.consumer_batch_size
  enabled                 = true
  function_response_types = ["ReportBatchItemFailures"]

  lifecycle {
    precondition {
      condition     = local.agent_invoke_read_timeout_seconds > local.agent_timeout_seconds
      error_message = "The consumer must wait longer for the agent than the agent timeout."
    }
    precondition {
      condition     = local.consumer_batch_size * local.agent_invoke_read_timeout_seconds < local.consumer_timeout_seconds
      error_message = "A full batch of serial agent invocations must finish within the consumer timeout."
    }
    precondition {
      condition     = var.ingest_queue_visibility_timeout_seconds >= 6 * local.consumer_timeout_seconds
      error_message = "The ingest queue visibility timeout must be at least six consumer timeouts."
    }
  }
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
  name               = "${local.name_prefix}-agentcore-exec-role"
  assume_role_policy = data.aws_iam_policy_document.agentcore_assume.json
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
    sid    = "BedrockInvokeInProfileRegions"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = ["arn:aws:bedrock:*::foundation-model/${var.bedrock_model_id}"]

    condition {
      test     = "ArnEquals"
      variable = "bedrock:InferenceProfileArn"
      values   = [local.inference_profile_arn]
    }
  }

  statement {
    sid       = "GuardrailApply"
    effect    = "Allow"
    actions   = ["bedrock:ApplyGuardrail"]
    resources = [aws_bedrock_guardrail.this.guardrail_arn]
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
# AgentCore resources (awscc) — Gateway + Memory, flag-gated via count, default
# false. With the flags false (count = 0) terraform validate / a dev plan
# contain ZERO AgentCore resources. The Strands agent itself now runs in the
# agent Lambda (see aws_lambda_function.agent), so there is no AgentCore
# Runtime here. awscc does NOT honour provider default_tags, so tags are set
# inline from local.tags.
#
# Resource type names + required args VERIFIED against the hashicorp/awscc
# provider docs (bedrockagentcore_gateway / _memory).
# =============================================================================
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
  event_expiry_duration = 7
  encryption_key_arn    = var.kms_key_arn

  tags = local.tags
}

# HMAC key for the AgentCore Memory actor/session ids. The value lives only in
# Secrets Manager and in the encrypted Terraform state; the agent Lambda only
# receives the secret ARN. Never output or log it.
resource "random_password" "agentcore_identity" {
  count = var.enable_agentcore_memory ? 1 : 0

  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "agentcore_identity" {
  count = var.enable_agentcore_memory ? 1 : 0

  name       = "${local.name_prefix}-agentcore-identity-key"
  kms_key_id = var.kms_key_arn
}

resource "aws_secretsmanager_secret_version" "agentcore_identity" {
  count = var.enable_agentcore_memory ? 1 : 0

  secret_id     = aws_secretsmanager_secret.agentcore_identity[0].id
  secret_string = random_password.agentcore_identity[0].result
}
