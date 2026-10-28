locals {
  name_prefix = "cdshack-urbanbot-${var.environment}"
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

data "archive_file" "follow_up" {
  type        = "zip"
  source_dir  = "${path.module}/src"
  output_path = "${path.module}/build/follow_up.zip"
}

resource "aws_cloudwatch_log_group" "follow_up" {
  name              = "/aws/lambda/${local.name_prefix}-follow-up"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "follow_up" {
  name               = "${local.name_prefix}-follow-up-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "follow_up" {
  statement {
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [var.incidents_table_arn]
  }
  statement {
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [var.reports_table_arn]
  }
  statement {
    actions   = ["dynamodb:GetItem"]
    resources = [var.users_table_arn]
  }
  statement {
    actions   = ["dynamodb:PutItem"]
    resources = [var.audit_log_table_arn]
  }
  statement {
    actions   = ["dynamodb:Query"]
    resources = ["${var.reports_table_arn}/index/by-user"]
  }
  statement {
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [var.kms_key_arn]
  }
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [var.outbound_function_arn]
  }
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.follow_up.arn}:*"]
  }
}

resource "aws_iam_policy" "follow_up" {
  name   = "${local.name_prefix}-follow-up-policy"
  policy = data.aws_iam_policy_document.follow_up.json
}

resource "aws_iam_role_policy_attachment" "follow_up" {
  role       = aws_iam_role.follow_up.name
  policy_arn = aws_iam_policy.follow_up.arn
}

resource "aws_lambda_function" "follow_up" {
  function_name    = "${local.name_prefix}-follow-up"
  role             = aws_iam_role.follow_up.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.follow_up.output_path
  source_code_hash = data.archive_file.follow_up.output_base64sha256
  timeout          = 60
  memory_size      = 256
  environment {
    variables = {
      INCIDENTS_TABLE                      = var.incidents_table_name
      REPORTS_TABLE                        = var.reports_table_name
      USERS_TABLE                          = var.users_table_name
      AUDIT_TABLE                          = var.audit_log_table_name
      OUTBOUND_FUNCTION_NAME               = var.outbound_function_name
      OUTBOUND_ORIGINATION_PHONE_NUMBER_ID = var.outbound_origination_phone_number_id
    }
  }
  depends_on = [aws_iam_role_policy_attachment.follow_up, aws_cloudwatch_log_group.follow_up]
}

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = ["arn:aws:scheduler:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:schedule-group/default"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${local.name_prefix}-follow-up-scheduler-role"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

resource "aws_iam_policy" "scheduler" {
  name = "${local.name_prefix}-follow-up-scheduler-policy"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["lambda:InvokeFunction"]
      Resource = [aws_lambda_function.follow_up.arn]
    }]
  })
}

resource "aws_iam_role_policy_attachment" "scheduler" {
  role       = aws_iam_role.scheduler.name
  policy_arn = aws_iam_policy.scheduler.arn
}
