data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_partition" "current" {}

locals {
  name_prefix = "cdshack-urbanbot-${var.environment}"
  account_id  = data.aws_caller_identity.current.account_id
  region      = data.aws_region.current.name
  partition   = data.aws_partition.current.partition

  social_messaging_source_arn = "arn:${local.partition}:social-messaging:${local.region}:${local.account_id}:*"
}

# =============================================================================
# KMS — Customer Managed Key used to encrypt S3, DynamoDB, SNS and SQS.
# =============================================================================
resource "aws_kms_key" "this" {
  description             = "${local.name_prefix} data encryption CMK (S3, DynamoDB, SNS, SQS)"
  enable_key_rotation     = true
  deletion_window_in_days = 7
}

resource "aws_kms_alias" "this" {
  name          = "alias/${local.name_prefix}-data-encryption"
  target_key_id = aws_kms_key.this.key_id
}

resource "aws_kms_key_policy" "this" {
  key_id = aws_kms_key.this.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EnableIAMUserPermissions"
        Effect = "Allow"
        Principal = {
          AWS = "arn:${local.partition}:iam::${local.account_id}:root"
        }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "AllowSocialMessagingUseOfKey"
        Effect = "Allow"
        Principal = {
          Service = "social-messaging.amazonaws.com"
        }
        Action = [
          "kms:GenerateDataKey*",
          "kms:Decrypt",
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = local.account_id
          }
          ArnLike = {
            "aws:SourceArn" = local.social_messaging_source_arn
          }
        }
      },
    ]
  })
}

# =============================================================================
# S3 — media bucket (images/audio ingested from WhatsApp).
# =============================================================================
resource "aws_s3_bucket" "media" {
  bucket = "${local.name_prefix}-media"
}

resource "aws_s3_bucket_ownership_controls" "media" {
  bucket = aws_s3_bucket.media.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "media" {
  bucket = aws_s3_bucket.media.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "media" {
  bucket = aws_s3_bucket.media.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "media" {
  bucket = aws_s3_bucket.media.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.this.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "media" {
  bucket = aws_s3_bucket.media.id

  rule {
    id     = "expire-raw"
    status = "Enabled"

    filter {
      prefix = "raw/"
    }

    expiration {
      days = var.media_retention_days
    }
  }
}

# =============================================================================
# DynamoDB — operational tables (all PAY_PER_REQUEST, CMK-encrypted, PITR on).
# =============================================================================
resource "aws_dynamodb_table" "reports" {
  name         = "${local.name_prefix}-reports"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "report_id"

  attribute {
    name = "report_id"
    type = "S"
  }

  attribute {
    name = "user_id"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "by-user"
    hash_key        = "user_id"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.this.arn
  }

  point_in_time_recovery {
    enabled = true
  }
}

resource "aws_dynamodb_table" "incidents" {
  name         = "${local.name_prefix}-incidents"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "incident_id"

  attribute {
    name = "incident_id"
    type = "S"
  }

  attribute {
    name = "geohash"
    type = "S"
  }

  attribute {
    name = "updated_at"
    type = "S"
  }

  global_secondary_index {
    name            = "by-geohash"
    hash_key        = "geohash"
    range_key       = "updated_at"
    projection_type = "ALL"
  }

  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.this.arn
  }

  point_in_time_recovery {
    enabled = true
  }
}

resource "aws_dynamodb_table" "places" {
  name         = "${local.name_prefix}-places"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_id"
  range_key    = "place_id"

  attribute {
    name = "user_id"
    type = "S"
  }

  attribute {
    name = "place_id"
    type = "S"
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.this.arn
  }

  point_in_time_recovery {
    enabled = true
  }
}

resource "aws_dynamodb_table" "users" {
  name         = "${local.name_prefix}-users"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_id"

  attribute {
    name = "user_id"
    type = "S"
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.this.arn
  }

  point_in_time_recovery {
    enabled = true
  }
}

resource "aws_dynamodb_table" "audit_log" {
  name         = "${local.name_prefix}-audit-log"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "entity_id"
  range_key    = "ts"

  attribute {
    name = "entity_id"
    type = "S"
  }

  attribute {
    name = "ts"
    type = "S"
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.this.arn
  }

  point_in_time_recovery {
    enabled = true
  }
}

# =============================================================================
# SNS — inbound topic (fan-out of inbound WhatsApp events).
# =============================================================================
resource "aws_sns_topic" "inbound" {
  name              = "${local.name_prefix}-inbound"
  kms_master_key_id = aws_kms_key.this.arn
}

resource "aws_sns_topic_policy" "inbound" {
  arn = aws_sns_topic.inbound.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowAccountOwner"
        Effect = "Allow"
        Principal = {
          AWS = "*"
        }
        Action = [
          "SNS:GetTopicAttributes",
          "SNS:SetTopicAttributes",
          "SNS:AddPermission",
          "SNS:RemovePermission",
          "SNS:DeleteTopic",
          "SNS:Subscribe",
          "SNS:ListSubscriptionsByTopic",
          "SNS:Publish",
        ]
        Resource = aws_sns_topic.inbound.arn
        Condition = {
          StringEquals = {
            "AWS:SourceOwner" = local.account_id
          }
        }
      },
      {
        Sid    = "AllowSocialMessagingPublish"
        Effect = "Allow"
        Principal = {
          Service = "social-messaging.amazonaws.com"
        }
        Action   = "sns:Publish"
        Resource = aws_sns_topic.inbound.arn
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = local.account_id
          }
          ArnLike = {
            "aws:SourceArn" = local.social_messaging_source_arn
          }
        }
      },
    ]
  })
}

# =============================================================================
# SQS FIFO — ingest queue + dead-letter queue.
# =============================================================================
resource "aws_sqs_queue" "ingest_dlq" {
  name                        = "${local.name_prefix}-ingest-dlq.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
  kms_master_key_id           = aws_kms_key.this.arn
}

resource "aws_sqs_queue" "ingest" {
  name                        = "${local.name_prefix}-ingest.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
  kms_master_key_id           = aws_kms_key.this.arn
  visibility_timeout_seconds  = 720

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ingest_dlq.arn
    maxReceiveCount     = 5
  })
}

# =============================================================================
# EventBridge — custom event bus for domain events.
# =============================================================================
resource "aws_cloudwatch_event_bus" "events" {
  name = "${local.name_prefix}-events"
}

resource "aws_dynamodb_table" "conversation_history" {
  count = var.enable_conversation_history ? 1 : 0

  name         = "${local.name_prefix}-conversation-history"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "citizen_id"
  range_key    = "ts"

  attribute {
    name = "citizen_id"
    type = "S"
  }
  attribute {
    name = "ts"
    type = "S"
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.this.arn
  }
}
