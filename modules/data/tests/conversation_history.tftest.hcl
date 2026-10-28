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

run "history_table" {
  command = plan
  variables {
    environment = "dev"
  }
  assert {
    condition     = aws_dynamodb_table.conversation_history.hash_key == "citizen_id" && aws_dynamodb_table.conversation_history.range_key == "ts"
    error_message = "History must be partitioned by pseudonymous citizen and sorted by timestamp."
  }
  assert {
    condition     = aws_dynamodb_table.conversation_history.ttl[0].enabled && aws_dynamodb_table.conversation_history.ttl[0].attribute_name == "expires_at"
    error_message = "History must expire through DynamoDB TTL."
  }
  assert {
    condition     = aws_dynamodb_table.conversation_history.server_side_encryption[0].enabled && aws_dynamodb_table.conversation_history.server_side_encryption[0].kms_key_arn == aws_kms_key.this.arn
    error_message = "History must use the project's encryption key."
  }
}
