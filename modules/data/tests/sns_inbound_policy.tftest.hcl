mock_provider "aws" {
  override_during = plan

  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
      arn        = "arn:aws:iam::123456789012:root"
      user_id    = "AIDAMOCK"
    }
  }

  mock_data "aws_region" {
    defaults = {
      name = "us-east-1"
    }
  }

  mock_data "aws_partition" {
    defaults = {
      partition = "aws"
    }
  }

  mock_resource "aws_sns_topic" {
    defaults = {
      arn = "arn:aws:sns:us-east-1:123456789012:cdshack-urbanbot-dev-inbound"
    }
  }

  mock_resource "aws_kms_key" {
    defaults = {
      arn    = "arn:aws:kms:us-east-1:123456789012:key/00000000-0000-0000-0000-000000000000"
      key_id = "00000000-0000-0000-0000-000000000000"
      id     = "00000000-0000-0000-0000-000000000000"
    }
  }
}

run "inbound_topic_policy_allows_social_messaging_publish" {
  command = plan

  variables {
    environment = "dev"
  }

  assert {
    condition = anytrue([
      for s in jsondecode(aws_sns_topic_policy.inbound.policy).Statement : (
        contains(flatten([try(s.Principal.Service, [])]), "social-messaging.amazonaws.com")
        && contains(flatten([s.Action]), "sns:Publish")
        && contains(flatten([try(s.Condition.StringEquals["aws:SourceAccount"], [])]), "123456789012")
        && contains(flatten([try(s.Condition.ArnLike["aws:SourceArn"], [])]), "arn:aws:social-messaging:us-east-1:123456789012:*")
      )
    ])
    error_message = "inbound SNS topic policy must allow sns:Publish to social-messaging.amazonaws.com scoped to the current account and region"
  }

  assert {
    condition = anytrue([
      for s in jsondecode(aws_kms_key_policy.this.policy).Statement : (
        contains(flatten([try(s.Principal.Service, [])]), "social-messaging.amazonaws.com")
        && contains(flatten([s.Action]), "kms:GenerateDataKey*")
        && contains(flatten([s.Action]), "kms:Decrypt")
        && contains(flatten([try(s.Condition.StringEquals["aws:SourceAccount"], [])]), "123456789012")
        && contains(flatten([try(s.Condition.ArnLike["aws:SourceArn"], [])]), "arn:aws:social-messaging:us-east-1:123456789012:*")
      )
    ])
    error_message = "data CMK policy must let social-messaging.amazonaws.com use the key to publish to the encrypted inbound topic"
  }
}

run "ingest_queue_visibility_covers_six_consumer_timeouts" {
  command = plan

  variables {
    environment = "dev"
  }

  assert {
    condition     = output.ingest_queue_visibility_timeout_seconds >= 6 * 120
    error_message = "ingest queue visibility timeout must be at least six 120 s consumer timeouts"
  }
}
