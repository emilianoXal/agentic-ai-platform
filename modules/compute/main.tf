locals {
  name_prefix = "cdshack-urbanbot-${var.environment}"
}

# =============================================================================
# Packaging — archive_file zips each handler's source dir at plan time into
# build/ (gitignored except .gitkeep); the CI plan job ships build/ as an
# artifact so apply on a clean runner finds the zips.
# =============================================================================
data "archive_file" "ingest" {
  type        = "zip"
  source_dir  = "${path.module}/src/ingest"
  output_path = "${path.module}/build/ingest.zip"
}

data "archive_file" "notifier" {
  type        = "zip"
  source_dir  = "${path.module}/src/notifier"
  output_path = "${path.module}/build/notifier.zip"
}

# =============================================================================
# CloudWatch log groups — created explicitly so IAM can scope to a known ARN
# and retention is managed (not auto-created by the Lambda service).
# =============================================================================
resource "aws_cloudwatch_log_group" "ingest" {
  name              = "/aws/lambda/${local.name_prefix}-ingest"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "notifier" {
  name              = "/aws/lambda/${local.name_prefix}-notifier"
  retention_in_days = var.log_retention_days
}

# =============================================================================
# Lambda assume-role policy (shared trust: lambda.amazonaws.com).
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
# ingest — IAM role + customer-managed least-privilege policy + attachment.
# =============================================================================
resource "aws_iam_role" "ingest" {
  name               = "${local.name_prefix}-ingest-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "ingest" {
  statement {
    sid    = "Logs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      aws_cloudwatch_log_group.ingest.arn,
      "${aws_cloudwatch_log_group.ingest.arn}:*",
    ]
  }

  statement {
    sid       = "EnqueueIngest"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [var.ingest_queue_arn]
  }

  statement {
    sid    = "DynamoUsersAudit"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
    ]
    resources = [
      var.users_table_arn,
      var.audit_table_arn,
    ]
  }

  statement {
    sid    = "KmsDataKey"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey",
    ]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_policy" "ingest" {
  name   = "${local.name_prefix}-ingest-policy"
  policy = data.aws_iam_policy_document.ingest.json
}

resource "aws_iam_role_policy_attachment" "ingest" {
  role       = aws_iam_role.ingest.name
  policy_arn = aws_iam_policy.ingest.arn
}

# =============================================================================
# notifier — IAM role + customer-managed least-privilege policy + attachment.
# No sns:Publish, no socialmessaging.
# =============================================================================
resource "aws_iam_role" "notifier" {
  name               = "${local.name_prefix}-notifier-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "notifier" {
  statement {
    sid    = "Logs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      aws_cloudwatch_log_group.notifier.arn,
      "${aws_cloudwatch_log_group.notifier.arn}:*",
    ]
  }

  statement {
    sid    = "DynamoUsersPlacesAudit"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:UpdateItem",
      "dynamodb:Query",
    ]
    resources = [
      var.users_table_arn,
      var.places_table_arn,
      var.audit_table_arn,
    ]
  }

  statement {
    sid    = "KmsDataKey"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey",
    ]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_policy" "notifier" {
  name   = "${local.name_prefix}-notifier-policy"
  policy = data.aws_iam_policy_document.notifier.json
}

resource "aws_iam_role_policy_attachment" "notifier" {
  role       = aws_iam_role.notifier.name
  policy_arn = aws_iam_policy.notifier.arn
}

# =============================================================================
# Lambda functions.
# =============================================================================
resource "aws_lambda_function" "ingest" {
  function_name    = "${local.name_prefix}-ingest"
  role             = aws_iam_role.ingest.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.ingest.output_path
  source_code_hash = data.archive_file.ingest.output_base64sha256
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      INGEST_QUEUE_URL    = var.ingest_queue_url
      USERS_TABLE         = var.users_table_name
      AUDIT_TABLE         = var.audit_table_name
      RATE_LIMIT_PER_HOUR = tostring(var.rate_limit_per_hour)
      MAX_TEXT_LEN        = tostring(var.max_text_len)
      LOG_LEVEL           = var.log_level
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.ingest,
    aws_iam_role_policy_attachment.ingest,
  ]
}

resource "aws_lambda_function" "notifier" {
  function_name    = "${local.name_prefix}-notifier"
  role             = aws_iam_role.notifier.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.notifier.output_path
  source_code_hash = data.archive_file.notifier.output_base64sha256
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      USERS_TABLE       = var.users_table_name
      PLACES_TABLE      = var.places_table_name
      AUDIT_TABLE       = var.audit_table_name
      DAILY_CAP_DEFAULT = tostring(var.daily_cap_default)
      LOG_LEVEL         = var.log_level
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.notifier,
    aws_iam_role_policy_attachment.notifier,
  ]
}

# =============================================================================
# Event wiring — ingest (SNS → Lambda).
# =============================================================================
resource "aws_lambda_permission" "ingest_sns" {
  statement_id  = "AllowSNSInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = var.inbound_topic_arn
}

resource "aws_sns_topic_subscription" "ingest" {
  topic_arn = var.inbound_topic_arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.ingest.arn
}

# =============================================================================
# Event wiring — notifier (EventBridge custom bus → Lambda).
# =============================================================================
resource "aws_cloudwatch_event_rule" "notifier" {
  name           = "${local.name_prefix}-notifier"
  event_bus_name = var.event_bus_name

  event_pattern = jsonencode({
    "detail-type" = ["StatusChanged", "IncidentNearby"]
  })
}

resource "aws_cloudwatch_event_target" "notifier" {
  rule           = aws_cloudwatch_event_rule.notifier.name
  event_bus_name = var.event_bus_name
  arn            = aws_lambda_function.notifier.arn
}

resource "aws_lambda_permission" "notifier_events" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.notifier.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.notifier.arn
}
