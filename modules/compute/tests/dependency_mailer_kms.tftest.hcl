provider "aws" {
  region                      = "us-east-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
  skip_region_validation      = true
}

variables {
  environment              = "dev"
  kms_key_arn              = "arn:aws:kms:us-east-1:123456789012:key/00000000-0000-0000-0000-000000000000"
  ingest_queue_url         = "https://sqs.us-east-1.amazonaws.com/123456789012/ingest.fifo"
  ingest_queue_arn         = "arn:aws:sqs:us-east-1:123456789012:ingest.fifo"
  inbound_topic_arn        = "arn:aws:sns:us-east-1:123456789012:inbound"
  media_bucket_name        = "cdshack-urbanbot-dev-media"
  media_bucket_arn         = "arn:aws:s3:::cdshack-urbanbot-dev-media"
  event_bus_name           = "events"
  event_bus_arn            = "arn:aws:events:us-east-1:123456789012:event-bus/events"
  pending_media_table_name = "pending-media"
  pending_media_table_arn  = "arn:aws:dynamodb:us-east-1:123456789012:table/pending-media"
  users_table_name         = "users"
  users_table_arn          = "arn:aws:dynamodb:us-east-1:123456789012:table/users"
  places_table_name        = "places"
  places_table_arn         = "arn:aws:dynamodb:us-east-1:123456789012:table/places"
  audit_table_name         = "audit"
  audit_table_arn          = "arn:aws:dynamodb:us-east-1:123456789012:table/audit"
  incidents_table_name     = "incidents"
  incidents_table_arn      = "arn:aws:dynamodb:us-east-1:123456789012:table/incidents"
  reports_table_name       = "reports"
  reports_table_arn        = "arn:aws:dynamodb:us-east-1:123456789012:table/reports"
  dependency_email_map = {
    bacheo = "obras@example.com"
  }
  dependency_fallback_email = "supervisor@example.com"
  dependency_mail_from      = "bot@example.com"
}

run "dependency_mailer_can_use_data_cmk" {
  command = plan

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "123456789012"
      arn        = "arn:aws:iam::123456789012:root"
      user_id    = "AIDAMOCK"
    }
  }

  override_data {
    target = data.aws_region.current
    values = {
      name = "us-east-1"
      id   = "use1-az1"
    }
  }

  override_data {
    target = data.aws_partition.current
    values = {
      partition  = "aws"
      dns_suffix = "amazonaws.com"
    }
  }

  assert {
    condition = anytrue([
      for s in jsondecode(data.aws_iam_policy_document.dependency_mailer_kms.json).Statement : (
        contains(flatten([s.Action]), "kms:Decrypt")
        && contains(flatten([s.Action]), "kms:GenerateDataKey")
        && contains(flatten([s.Resource]), var.kms_key_arn)
        && !contains(flatten([s.Resource]), "*")
      )
    ])
    error_message = "dependency_mailer KMS grant must Decrypt and GenerateDataKey only on the data CMK"
  }

  assert {
    condition = contains(
      data.aws_iam_policy_document.dependency_mailer.source_policy_documents,
      data.aws_iam_policy_document.dependency_mailer_kms.json,
    )
    error_message = "dependency_mailer role policy must include the data CMK grant"
  }
}
