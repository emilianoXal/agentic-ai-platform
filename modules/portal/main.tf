# =============================================================================
# Portal module — officials' dashboard backend and hosting.
#
# Manages:
#   - Cognito user pool for staff (groups agency / official / admin)
#   - AppSync GraphQL API (Cognito auth + IAM for the stream publisher)
#   - dashboard_api Lambda (queries, status changes, demo seed) and
#     stream_publisher Lambda (incidents stream -> AppSync subscription)
#   - Amazon Location API key restricted to map tiles and reverse geocoding
#   - Amplify Hosting (manual zip deployments) for the Angular build
#
# Dependencies: data (tables, streams, CMK, event bus).
# =============================================================================
locals {
  name_prefix = "cdshack-urbanbot-${var.environment}"

  # awscc does not honour provider default_tags; same six tags inline.
  tags = {
    Project     = "cdshack-urbanbot"
    Agente      = "urbanbot"
    Environment = var.environment
    ManagedBy   = "terraform"
    Repo        = "hackaton-aws-cds-agentic-ai/agentic-ai-platform"
    Owner       = "xaldigital"
  }

  dashboard_origin = var.enable_hosting ? "https://main.${aws_amplify_app.dashboard[0].default_domain}" : null
  maps_referers    = [for origin in compact(concat(var.local_dev_origins, [local.dashboard_origin])) : "${origin}/*"]
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# --- Packaging ---------------------------------------------------------------
data "archive_file" "dashboard_api" {
  type        = "zip"
  source_dir  = "${path.module}/src/dashboard_api"
  output_path = "${path.module}/build/dashboard_api.zip"
}

data "archive_file" "stream_publisher" {
  type        = "zip"
  source_dir  = "${path.module}/src/stream_publisher"
  output_path = "${path.module}/build/stream_publisher.zip"
}

# --- Log groups --------------------------------------------------------------
resource "aws_cloudwatch_log_group" "dashboard_api" {
  name              = "/aws/lambda/${local.name_prefix}-dashboard-api"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "stream_publisher" {
  name              = "/aws/lambda/${local.name_prefix}-stream-publisher"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "appsync" {
  name              = "/aws/appsync/apis/${aws_appsync_graphql_api.this.id}"
  retention_in_days = var.log_retention_days
}

# =============================================================================
# Cognito — staff sign-in. Users are created by an admin (no self sign-up).
# =============================================================================
resource "aws_cognito_user_pool" "staff" {
  name                     = "${local.name_prefix}-staff"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  deletion_protection      = var.user_pool_deletion_protection
  mfa_configuration        = "OPTIONAL"

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  software_token_mfa_configuration {
    enabled = true
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 3
  }

  user_pool_add_ons {
    advanced_security_mode = "OFF"
  }

  # Agency operators carry their agency slug (e.g. organismo-de-agua); the API scopes on it.
  schema {
    name                     = "agency_id"
    attribute_data_type      = "String"
    mutable                  = true
    developer_only_attribute = false

    string_attribute_constraints {
      min_length = 0
      max_length = 64
    }
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
}

resource "aws_cognito_user_pool_client" "dashboard" {
  name                          = "${local.name_prefix}-dashboard"
  user_pool_id                  = aws_cognito_user_pool.staff.id
  generate_secret               = false
  prevent_user_existence_errors = "ENABLED"
  explicit_auth_flows           = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  read_attributes               = ["email", "name", "custom:agency_id"]
  write_attributes              = ["name"]
  access_token_validity         = 60
  id_token_validity             = 60
  refresh_token_validity        = 12

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "hours"
  }
}

resource "aws_cognito_user_group" "this" {
  for_each = {
    agency   = "Agency operators: incidents routed to their custom:agency_id only"
    official = "Municipal supervisors: every agency, escalation"
    admin    = "UrbanBot administrators: configuration and demo data"
  }

  name         = each.key
  description  = each.value
  user_pool_id = aws_cognito_user_pool.staff.id
}

# Staff accounts managed as code (the human SSO role cannot call Cognito Admin APIs).
resource "aws_cognito_user" "staff" {
  for_each = var.staff_users

  user_pool_id             = aws_cognito_user_pool.staff.id
  username                 = each.key
  desired_delivery_mediums = ["EMAIL"]

  attributes = merge(
    {
      email          = each.key
      email_verified = "true"
      name           = each.value.name
    },
    each.value.agency_id == null ? {} : { agency_id = each.value.agency_id },
  )

  # Users change their temporary password on first sign-in; keep Terraform out of it.
  lifecycle {
    ignore_changes = [password, temporary_password]
  }
}

resource "aws_cognito_user_in_group" "staff" {
  for_each = var.staff_users

  user_pool_id = aws_cognito_user_pool.staff.id
  username     = aws_cognito_user.staff[each.key].username
  group_name   = aws_cognito_user_group.this[each.value.group].name
}

# =============================================================================
# IAM — one role per principal, least privilege.
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

data "aws_iam_policy_document" "appsync_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["appsync.amazonaws.com"]
    }
  }
}

# --- dashboard_api: incidents/reports/audit/users R/W, bus PutEvents, reverse geocode.
resource "aws_iam_role" "dashboard_api" {
  name               = "${local.name_prefix}-dashboard-api-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "dashboard_api" {
  statement {
    sid    = "Tables"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:BatchGetItem",
      "dynamodb:Query",
      "dynamodb:Scan",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:BatchWriteItem",
    ]
    resources = [
      var.incidents_table_arn,
      var.reports_table_arn,
      var.audit_log_table_arn,
      var.users_table_arn,
    ]
  }

  statement {
    sid       = "Kms"
    effect    = "Allow"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [var.kms_key_arn]
  }

  statement {
    sid       = "Events"
    effect    = "Allow"
    actions   = ["events:PutEvents"]
    resources = [var.events_bus_arn]
  }

  statement {
    sid       = "Tracing"
    effect    = "Allow"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"] # X-Ray trace APIs do not support resource-level permissions.
  }

  statement {
    sid       = "ReverseGeocode"
    effect    = "Allow"
    actions   = ["geo-places:ReverseGeocode"]
    resources = ["arn:aws:geo-places:${data.aws_region.current.name}::provider/default"]
  }

  statement {
    sid       = "Logs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.dashboard_api.arn}:*"]
  }
}

resource "aws_iam_policy" "dashboard_api" {
  name   = "${local.name_prefix}-dashboard-api-policy"
  policy = data.aws_iam_policy_document.dashboard_api.json
}

resource "aws_iam_role_policy_attachment" "dashboard_api" {
  role       = aws_iam_role.dashboard_api.name
  policy_arn = aws_iam_policy.dashboard_api.arn
}

# --- stream_publisher: read the incidents stream, call one AppSync field.
resource "aws_iam_role" "stream_publisher" {
  name               = "${local.name_prefix}-stream-publisher-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "stream_publisher" {
  statement {
    sid    = "Stream"
    effect = "Allow"
    actions = [
      "dynamodb:DescribeStream",
      "dynamodb:GetRecords",
      "dynamodb:GetShardIterator",
      "dynamodb:ListStreams",
    ]
    resources = [var.incidents_stream_arn]
  }

  statement {
    sid       = "Kms"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = [var.kms_key_arn]
  }

  statement {
    sid       = "PublishChange"
    effect    = "Allow"
    actions   = ["appsync:GraphQL"]
    resources = ["${aws_appsync_graphql_api.this.arn}/types/Mutation/fields/publishIncidentChange"]
  }

  statement {
    sid       = "Logs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.stream_publisher.arn}:*"]
  }
}

resource "aws_iam_policy" "stream_publisher" {
  name   = "${local.name_prefix}-stream-publisher-policy"
  policy = data.aws_iam_policy_document.stream_publisher.json
}

resource "aws_iam_role_policy_attachment" "stream_publisher" {
  role       = aws_iam_role.stream_publisher.name
  policy_arn = aws_iam_policy.stream_publisher.arn
}

# --- AppSync: invoke the dashboard_api Lambda.
resource "aws_iam_role" "appsync_datasource" {
  name               = "${local.name_prefix}-appsync-datasource-role"
  assume_role_policy = data.aws_iam_policy_document.appsync_assume.json
}

data "aws_iam_policy_document" "appsync_datasource" {
  statement {
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.dashboard_api.arn]
  }
}

resource "aws_iam_policy" "appsync_datasource" {
  name   = "${local.name_prefix}-appsync-datasource-policy"
  policy = data.aws_iam_policy_document.appsync_datasource.json
}

resource "aws_iam_role_policy_attachment" "appsync_datasource" {
  role       = aws_iam_role.appsync_datasource.name
  policy_arn = aws_iam_policy.appsync_datasource.arn
}

# --- AppSync: write its own logs (FSBP AppSync.2).
resource "aws_iam_role" "appsync_logs" {
  name               = "${local.name_prefix}-appsync-logs-role"
  assume_role_policy = data.aws_iam_policy_document.appsync_assume.json
}

data "aws_iam_policy_document" "appsync_logs" {
  statement {
    effect    = "Allow"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/appsync/apis/*"]
  }
}

resource "aws_iam_policy" "appsync_logs" {
  name   = "${local.name_prefix}-appsync-logs-policy"
  policy = data.aws_iam_policy_document.appsync_logs.json
}

resource "aws_iam_role_policy_attachment" "appsync_logs" {
  role       = aws_iam_role.appsync_logs.name
  policy_arn = aws_iam_policy.appsync_logs.arn
}

# =============================================================================
# Lambdas.
# =============================================================================
resource "aws_lambda_function" "dashboard_api" {
  function_name    = "${local.name_prefix}-dashboard-api"
  description      = "Dashboard API: incident queries, status changes, demo data"
  role             = aws_iam_role.dashboard_api.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.dashboard_api.output_path
  source_code_hash = data.archive_file.dashboard_api.output_base64sha256
  timeout          = 30
  memory_size      = 512

  environment {
    variables = {
      INCIDENTS_TABLE_NAME = var.incidents_table_name
      REPORTS_TABLE_NAME   = var.reports_table_name
      AUDIT_TABLE_NAME     = var.audit_log_table_name
      USERS_TABLE_NAME     = var.users_table_name
      EVENT_BUS_NAME       = var.events_bus_name
      ROUTING_RULES_JSON   = var.routing_rules_json
      FOLLOW_UP_HOURS      = tostring(var.follow_up_hours)
      LOG_LEVEL            = var.log_level
    }
  }

  tracing_config {
    mode = "Active"
  }

  depends_on = [aws_cloudwatch_log_group.dashboard_api, aws_iam_role_policy_attachment.dashboard_api]
}

resource "aws_lambda_function" "stream_publisher" {
  function_name    = "${local.name_prefix}-stream-publisher"
  description      = "Incidents stream to AppSync subscription (real-time dashboard)"
  role             = aws_iam_role.stream_publisher.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.stream_publisher.output_path
  source_code_hash = data.archive_file.stream_publisher.output_base64sha256
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      GRAPHQL_URL = aws_appsync_graphql_api.this.uris["GRAPHQL"]
      LOG_LEVEL   = var.log_level
    }
  }

  depends_on = [aws_cloudwatch_log_group.stream_publisher, aws_iam_role_policy_attachment.stream_publisher]
}

resource "aws_lambda_event_source_mapping" "incidents_stream" {
  event_source_arn               = var.incidents_stream_arn
  function_name                  = aws_lambda_function.stream_publisher.arn
  starting_position              = "LATEST"
  batch_size                     = 10
  maximum_retry_attempts         = 3
  bisect_batch_on_function_error = true
  function_response_types        = ["ReportBatchItemFailures"]
}

# =============================================================================
# AppSync GraphQL API.
# =============================================================================
resource "aws_appsync_graphql_api" "this" {
  name                = "${local.name_prefix}-dashboard"
  authentication_type = "AMAZON_COGNITO_USER_POOLS"
  schema              = file("${path.module}/schema.graphql")
  # X-Ray on AppSync needs the AWSServiceRoleForAppSync service-linked role, and the
  # governance policy does not let the pipeline create it. Lambda keeps its own tracing.
  xray_enabled = false

  user_pool_config {
    user_pool_id   = aws_cognito_user_pool.staff.id
    aws_region     = data.aws_region.current.name
    default_action = "ALLOW"
  }

  additional_authentication_provider {
    authentication_type = "AWS_IAM"
  }

  log_config {
    cloudwatch_logs_role_arn = aws_iam_role.appsync_logs.arn
    field_log_level          = "ERROR"
  }
}

resource "aws_appsync_datasource" "dashboard_api" {
  api_id           = aws_appsync_graphql_api.this.id
  name             = "dashboard_api"
  type             = "AWS_LAMBDA"
  service_role_arn = aws_iam_role.appsync_datasource.arn

  lambda_config {
    function_arn = aws_lambda_function.dashboard_api.arn
  }
}

resource "aws_appsync_datasource" "none" {
  api_id = aws_appsync_graphql_api.this.id
  name   = "local_publish"
  type   = "NONE"
}

# Direct Lambda resolvers (no mapping templates): AppSync passes arguments,
# identity and info to the handler, which dispatches on the field.
resource "aws_appsync_resolver" "lambda" {
  for_each = {
    "Query.listIncidents"           = ["Query", "listIncidents"]
    "Query.getIncident"             = ["Query", "getIncident"]
    "Query.listAgencies"            = ["Query", "listAgencies"]
    "Mutation.updateIncidentStatus" = ["Mutation", "updateIncidentStatus"]
    "Mutation.addIncidentComment"   = ["Mutation", "addIncidentComment"]
    "Mutation.escalateIncident"     = ["Mutation", "escalateIncident"]
    "Mutation.seedDemoData"         = ["Mutation", "seedDemoData"]
    "Mutation.resetDemoData"        = ["Mutation", "resetDemoData"]
  }

  api_id      = aws_appsync_graphql_api.this.id
  type        = each.value[0]
  field       = each.value[1]
  data_source = aws_appsync_datasource.dashboard_api.name
}

# Local resolver: echoes the change so onIncidentChange subscribers receive it.
resource "aws_appsync_resolver" "publish_change" {
  api_id      = aws_appsync_graphql_api.this.id
  type        = "Mutation"
  field       = "publishIncidentChange"
  data_source = aws_appsync_datasource.none.name
  code        = <<-JS
    export function request(ctx) {
      return { payload: ctx.args };
    }
    export function response(ctx) {
      return ctx.result;
    }
  JS

  runtime {
    name            = "APPSYNC_JS"
    runtime_version = "1.0.0"
  }
}

# =============================================================================
# WAF — regional ACL in front of AppSync (FSBP APIGateway.4-equivalent).
# =============================================================================
resource "aws_wafv2_web_acl" "api" {
  name  = "${local.name_prefix}-dashboard-api-acl"
  scope = "REGIONAL"

  default_action {
    allow {}
  }

  rule {
    name     = "aws-common"
    priority = 1

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-api-common"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "rate-limit"
    priority = 2

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = 2000
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-api-rate"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.name_prefix}-api-acl"
    sampled_requests_enabled   = true
  }
}

resource "aws_wafv2_web_acl_association" "api" {
  resource_arn = aws_appsync_graphql_api.this.arn
  web_acl_arn  = aws_wafv2_web_acl.api.arn
}

# =============================================================================
# Amazon Location — browser API key for map tiles and reverse geocoding only,
# restricted to the dashboard origins (a public client key by design).
# =============================================================================
resource "awscc_location_api_key" "maps" {
  key_name    = "${local.name_prefix}-dashboard-maps"
  description = "UrbanBot dashboard: map tiles and reverse geocoding"
  no_expiry   = true

  restrictions = {
    allow_actions = [
      "geo-maps:GetTile",
      "geo-maps:GetStaticMap",
      "geo-places:ReverseGeocode",
    ]
    allow_resources = [
      "arn:aws:geo-maps:${data.aws_region.current.name}::provider/default",
      "arn:aws:geo-places:${data.aws_region.current.name}::provider/default",
    ]
    allow_referers = local.maps_referers
  }

  tags = [for key, value in local.tags : { key = key, value = value }]
}

# =============================================================================
# Hosting — Amplify Hosting with manual (zip) deployments from the main branch
# pipeline. The governance policy grants amplify:* but not cloudfront:*, so the
# managed CDN of Amplify replaces a self-managed S3 + CloudFront distribution.
# =============================================================================
resource "aws_amplify_app" "dashboard" {
  count       = var.enable_hosting ? 1 : 0
  name        = "${local.name_prefix}-dashboard"
  description = "UrbanBot officials' dashboard (Angular)"
  platform    = "WEB"

  # Single-page app: every path without a file extension serves index.html.
  # Static extensions are served as files (mjs = the MapLibre web worker).
  custom_rule {
    source = "</^[^.]+$|\\.(?!(css|gif|ico|jpg|jpeg|js|mjs|json|map|png|svg|txt|webp|woff|woff2|ttf)$)([^.]+$)/>"
    target = "/index.html"
    status = "200"
  }

  custom_headers = <<-YAML
    customHeaders:
      - pattern: '**/*'
        headers:
          - key: Strict-Transport-Security
            value: max-age=31536000; includeSubDomains
          - key: X-Content-Type-Options
            value: nosniff
          - key: X-Frame-Options
            value: DENY
          - key: Referrer-Policy
            value: strict-origin-when-cross-origin
      - pattern: '**/*.mjs'
        headers:
          - key: Content-Type
            value: text/javascript
      - pattern: 'config.json'
        headers:
          - key: Cache-Control
            value: no-cache
      - pattern: 'index.html'
        headers:
          - key: Cache-Control
            value: no-cache
  YAML
}

resource "aws_amplify_branch" "main" {
  count             = var.enable_hosting ? 1 : 0
  app_id            = aws_amplify_app.dashboard[0].id
  branch_name       = "main"
  stage             = var.environment == "prod" ? "PRODUCTION" : "DEVELOPMENT"
  enable_auto_build = false
}
