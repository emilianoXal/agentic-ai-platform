mock_provider "aws" {
  override_during = plan

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

mock_provider "awscc" {
  override_during = plan

  mock_resource "awscc_bedrockagentcore_memory" {
    defaults = {
      encryption_key_arn = null
    }
  }
}

mock_provider "random" {}

variables {
  enable_agentcore_memory                 = true
  environment                             = "dev"
  kms_key_arn                             = "arn:aws:kms:us-east-1:123456789012:key/00000000-0000-0000-0000-000000000000"
  reports_table_name                      = "reports"
  reports_table_arn                       = "arn:aws:dynamodb:us-east-1:123456789012:table/reports"
  incidents_table_name                    = "incidents"
  incidents_table_arn                     = "arn:aws:dynamodb:us-east-1:123456789012:table/incidents"
  places_table_name                       = "places"
  places_table_arn                        = "arn:aws:dynamodb:us-east-1:123456789012:table/places"
  users_table_name                        = "users"
  users_table_arn                         = "arn:aws:dynamodb:us-east-1:123456789012:table/users"
  audit_log_table_name                    = "audit"
  audit_log_table_arn                     = "arn:aws:dynamodb:us-east-1:123456789012:table/audit"
  ingest_queue_arn                        = "arn:aws:sqs:us-east-1:123456789012:ingest.fifo"
  ingest_queue_url                        = "https://sqs.us-east-1.amazonaws.com/123456789012/ingest.fifo"
  ingest_queue_visibility_timeout_seconds = 720
  events_bus_name                         = "events"
  events_bus_arn                          = "arn:aws:events:us-east-1:123456789012:event-bus/events"
  outbound_function_name                  = "outbound"
  outbound_function_arn                   = "arn:aws:lambda:us-east-1:123456789012:function:outbound"
}

run "memory_uses_aws_default_encryption" {
  command = plan

  assert {
    condition     = awscc_bedrockagentcore_memory.this[0].encryption_key_arn == null
    error_message = "AgentCore Memory must use AWS default encryption without a customer-managed key."
  }

  assert {
    condition     = awscc_bedrockagentcore_memory.this[0].name == "cdshack_urbanbot_dev_memory_aws_encrypted"
    error_message = "The new memory must avoid the name held by the failed creation outside Terraform state."
  }

  assert {
    condition     = aws_secretsmanager_secret.agentcore_identity[0].kms_key_id == var.kms_key_arn
    error_message = "The HMAC identity secret must retain the project customer-managed key."
  }
}
