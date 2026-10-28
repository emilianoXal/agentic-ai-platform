locals {
  name_prefix = "cdshack-urbanbot-${var.environment}"
}

data "aws_partition" "current" {}
data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

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

data "archive_file" "outbound" {
  type        = "zip"
  source_dir  = "${path.module}/src/outbound"
  output_path = "${path.module}/build/outbound.zip"
}

data "archive_file" "dependency_mailer" {
  type        = "zip"
  source_dir  = "${path.module}/src/dependency_mailer"
  output_path = "${path.module}/build/dependency-mailer.zip"
}

data "archive_file" "media_download" {
  type        = "zip"
  source_dir  = "${path.module}/src/media_download"
  output_path = "${path.module}/build/media-download.zip"
}

data "archive_file" "media" {
  type        = "zip"
  source_dir  = "${path.module}/src/media"
  output_path = "${path.module}/build/media.zip"
}

data "archive_file" "pillow_layer" {
  type        = "zip"
  source_dir  = "${path.module}/layers/pillow"
  output_path = "${path.module}/build/pillow-layer.zip"
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

resource "aws_cloudwatch_log_group" "outbound" {
  name              = "/aws/lambda/${local.name_prefix}-outbound"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "dependency_mailer" {
  name              = "/aws/lambda/${local.name_prefix}-dependency-mailer"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "media_download" {
  name              = "/aws/lambda/${local.name_prefix}-media-download"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "media" {
  name              = "/aws/lambda/${local.name_prefix}-media-sanitize"
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

data "aws_iam_policy_document" "states_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
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

  statement {
    sid       = "RememberPendingMedia"
    effect    = "Allow"
    actions   = ["dynamodb:UpdateItem"]
    resources = [var.pending_media_table_arn]
  }

  statement {
    sid       = "StartMediaSanitization"
    effect    = "Allow"
    actions   = ["states:StartExecution"]
    resources = [aws_sfn_state_machine.media.arn]
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

  statement {
    sid       = "InvokeOutbound"
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.outbound.arn]
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

resource "aws_iam_role" "dependency_mailer" {
  name               = "${local.name_prefix}-dependency-mailer-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_sesv2_email_identity" "dependency_mail" {
  for_each = toset(concat(
    values(var.dependency_email_map),
    [var.dependency_fallback_email, var.dependency_mail_from],
  ))

  email_identity = each.value
}

data "aws_iam_policy_document" "dependency_mailer" {
  statement {
    sid    = "Logs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      aws_cloudwatch_log_group.dependency_mailer.arn,
      "${aws_cloudwatch_log_group.dependency_mailer.arn}:*",
    ]
  }

  statement {
    sid    = "IncidentAndDedupState"
    effect = "Allow"
    actions = [
      "dynamodb:DeleteItem",
      "dynamodb:GetItem",
      "dynamodb:PutItem",
    ]
    resources = [
      var.incidents_table_arn,
      var.audit_table_arn,
    ]
  }

  statement {
    sid       = "SendDependencyEmail"
    effect    = "Allow"
    actions   = ["ses:SendEmail"]
    resources = [for identity in aws_sesv2_email_identity.dependency_mail : identity.arn]
  }
}

resource "aws_iam_policy" "dependency_mailer" {
  name   = "${local.name_prefix}-dependency-mailer-policy"
  policy = data.aws_iam_policy_document.dependency_mailer.json
}

resource "aws_iam_role_policy_attachment" "dependency_mailer" {
  role       = aws_iam_role.dependency_mailer.name
  policy_arn = aws_iam_policy.dependency_mailer.arn
}

resource "aws_iam_role" "media_download" {
  name               = "${local.name_prefix}-media-download-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "media_download" {
  statement {
    sid       = "Logs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.media_download.arn}:*"]
  }

  statement {
    sid     = "DownloadWhatsAppMedia"
    effect  = "Allow"
    actions = ["social-messaging:GetWhatsAppMessageMedia"]
    resources = [
      "arn:${data.aws_partition.current.partition}:social-messaging:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:phone-number-id/*"
    ]
  }

  statement {
    sid       = "StoreRawMedia"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${var.media_bucket_arn}/raw/*"]
  }

  statement {
    sid       = "EncryptRawMedia"
    effect    = "Allow"
    actions   = ["kms:Encrypt", "kms:GenerateDataKey"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_policy" "media_download" {
  name   = "${local.name_prefix}-media-download-policy"
  policy = data.aws_iam_policy_document.media_download.json
}

resource "aws_iam_role_policy_attachment" "media_download" {
  role       = aws_iam_role.media_download.name
  policy_arn = aws_iam_policy.media_download.arn
}

resource "aws_iam_role" "media" {
  name               = "${local.name_prefix}-media-sanitize-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "media" {
  statement {
    sid       = "Logs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.media.arn}:*"]
  }

  statement {
    sid    = "ReadAndSanitizeMedia"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = [
      "${var.media_bucket_arn}/raw/*",
      "${var.media_bucket_arn}/sanitized/*",
    ]
  }

  statement {
    sid       = "MediaEncryption"
    effect    = "Allow"
    actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_policy" "media" {
  name   = "${local.name_prefix}-media-sanitize-policy"
  policy = data.aws_iam_policy_document.media.json
}

resource "aws_iam_role_policy_attachment" "media" {
  role       = aws_iam_role.media.name
  policy_arn = aws_iam_policy.media.arn
}

resource "aws_iam_role" "media_workflow" {
  name               = "${local.name_prefix}-media-workflow-role"
  assume_role_policy = data.aws_iam_policy_document.states_assume.json
}

data "aws_iam_policy_document" "media_workflow" {
  statement {
    sid     = "InvokeMediaFunctions"
    effect  = "Allow"
    actions = ["lambda:InvokeFunction"]
    resources = [
      aws_lambda_function.media_download.arn,
      aws_lambda_function.media.arn,
    ]
  }

  statement {
    sid       = "DetectSensitiveRegions"
    effect    = "Allow"
    actions   = ["rekognition:DetectFaces", "rekognition:DetectText"]
    resources = ["*"]
  }

  statement {
    sid       = "ReadRawMedia"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${var.media_bucket_arn}/raw/*"]
  }

  statement {
    sid       = "DecryptRawMedia"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_policy" "media_workflow" {
  name   = "${local.name_prefix}-media-workflow-policy"
  policy = data.aws_iam_policy_document.media_workflow.json
}

resource "aws_iam_role_policy_attachment" "media_workflow" {
  role       = aws_iam_role.media_workflow.name
  policy_arn = aws_iam_policy.media_workflow.arn
}

# =============================================================================
# outbound — IAM role + customer-managed least-privilege policy + attachment.
# The ONE and only role that holds social-messaging:SendWhatsAppMessage (RB-01).
# =============================================================================
resource "aws_iam_role" "outbound" {
  name               = "${local.name_prefix}-outbound-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "outbound" {
  statement {
    sid    = "Logs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      aws_cloudwatch_log_group.outbound.arn,
      "${aws_cloudwatch_log_group.outbound.arn}:*",
    ]
  }

  # This role intentionally has NO kms grant: it touches no CMK-encrypted
  # DynamoDB/SQS/S3. EUM's own delivery/media encryption is covered by the
  # AllowSocialMessagingUseOfKey grant on the CMK key policy in modules/data,
  # which grants the social-messaging.amazonaws.com service principal (not this
  # role); text-only SendWhatsAppMessage needs no caller-side KMS.
  statement {
    sid    = "SendWhatsApp"
    effect = "Allow"
    # IAM service prefix is "social-messaging" (with hyphen) per the AWS
    # service-authorization reference — NOT "socialmessaging" (that's only the
    # boto3 client name). The wrong prefix grants nothing -> AccessDenied.
    actions = ["social-messaging:SendWhatsAppMessage"]
    # VP-4: no confirmed resource-level ARN support for this action in the EUM
    # Social service-authorization reference; tighten Resource to the
    # phone-number-id ARN if/when the service adds it. PostWhatsAppMessageMedia
    # is intentionally NOT granted (text-only path).
    resources = ["*"]
  }
}

resource "aws_iam_policy" "outbound" {
  name   = "${local.name_prefix}-outbound-policy"
  policy = data.aws_iam_policy_document.outbound.json
}

resource "aws_iam_role_policy_attachment" "outbound" {
  role       = aws_iam_role.outbound.name
  policy_arn = aws_iam_policy.outbound.arn
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
      INGEST_QUEUE_URL        = var.ingest_queue_url
      USERS_TABLE             = var.users_table_name
      AUDIT_TABLE             = var.audit_table_name
      RATE_LIMIT_PER_HOUR     = tostring(var.rate_limit_per_hour)
      MAX_TEXT_LEN            = tostring(var.max_text_len)
      MEDIA_BUCKET            = var.media_bucket_name
      MEDIA_STATE_MACHINE_ARN = aws_sfn_state_machine.media.arn
      PENDING_MEDIA_TABLE     = var.pending_media_table_name
      LOG_LEVEL               = var.log_level
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

      OUTBOUND_FUNCTION_NAME               = aws_lambda_function.outbound.function_name
      OUTBOUND_ORIGINATION_PHONE_NUMBER_ID = var.outbound_origination_phone_number_id
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.notifier,
    aws_iam_role_policy_attachment.notifier,
  ]
}

resource "aws_lambda_function" "outbound" {
  function_name    = "${local.name_prefix}-outbound"
  role             = aws_iam_role.outbound.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.outbound.output_path
  source_code_hash = data.archive_file.outbound.output_base64sha256
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      META_API_VERSION = var.meta_api_version
      LOG_LEVEL        = var.log_level
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.outbound,
    aws_iam_role_policy_attachment.outbound,
  ]
}

resource "aws_lambda_function" "dependency_mailer" {
  function_name    = "${local.name_prefix}-dependency-mailer"
  role             = aws_iam_role.dependency_mailer.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.dependency_mailer.output_path
  source_code_hash = data.archive_file.dependency_mailer.output_base64sha256
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      INCIDENTS_TABLE           = var.incidents_table_name
      AUDIT_TABLE               = var.audit_table_name
      DEPENDENCY_EMAIL_MAP      = jsonencode(var.dependency_email_map)
      DEPENDENCY_FALLBACK_EMAIL = var.dependency_fallback_email
      MAIL_FROM                 = var.dependency_mail_from
      PORTAL_URL                = "${var.portal_url}/incidents"
      LOG_LEVEL                 = var.log_level
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.dependency_mailer,
    aws_iam_role_policy_attachment.dependency_mailer,
  ]
}

resource "aws_lambda_layer_version" "pillow" {
  layer_name          = "${local.name_prefix}-pillow"
  filename            = data.archive_file.pillow_layer.output_path
  source_code_hash    = data.archive_file.pillow_layer.output_base64sha256
  compatible_runtimes = ["python3.12"]
}

resource "aws_lambda_function" "media_download" {
  function_name    = "${local.name_prefix}-media-download"
  role             = aws_iam_role.media_download.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.media_download.output_path
  source_code_hash = data.archive_file.media_download.output_base64sha256
  timeout          = 60
  memory_size      = 256

  environment {
    variables = {
      LOG_LEVEL = var.log_level
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.media_download,
    aws_iam_role_policy_attachment.media_download,
  ]
}

resource "aws_lambda_function" "media" {
  function_name    = "${local.name_prefix}-media-sanitize"
  role             = aws_iam_role.media.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.media.output_path
  source_code_hash = data.archive_file.media.output_base64sha256
  layers           = [aws_lambda_layer_version.pillow.arn]
  timeout          = 60
  memory_size      = 1024

  environment {
    variables = {
      LOG_LEVEL = var.log_level
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.media,
    aws_iam_role_policy_attachment.media,
  ]
}

resource "aws_sfn_state_machine" "media" {
  name     = "${local.name_prefix}-media-sanitize"
  role_arn = aws_iam_role.media_workflow.arn
  definition = templatefile("${path.module}/media_state_machine.asl.json.tftpl", {
    download_lambda_arn = aws_lambda_function.media_download.arn
    sanitize_lambda_arn = aws_lambda_function.media.arn
  })

  depends_on = [aws_iam_role_policy_attachment.media_workflow]
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

resource "aws_cloudwatch_event_rule" "dependency_mailer" {
  name           = "${local.name_prefix}-dependency-mailer"
  event_bus_name = var.event_bus_name

  event_pattern = jsonencode({
    "detail-type" = ["StatusChanged", "IncidentEscalated", "IncidentNearby"]
  })
}

resource "aws_cloudwatch_event_target" "dependency_mailer" {
  rule           = aws_cloudwatch_event_rule.dependency_mailer.name
  event_bus_name = var.event_bus_name
  arn            = aws_lambda_function.dependency_mailer.arn
}

resource "aws_lambda_permission" "dependency_mailer_events" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dependency_mailer.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.dependency_mailer.arn
}
