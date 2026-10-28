mock_provider "aws" {
  override_during = plan

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

mock_provider "awscc" {}

mock_provider "random" {}

variables {
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
  pending_media_table_name                = "pending-media"
  pending_media_table_arn                 = "arn:aws:dynamodb:us-east-1:123456789012:table/pending-media"
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

run "register_consent_wires_users_table_and_agent" {
  command = plan

  assert {
    condition     = aws_lambda_function.register_consent.function_name == "cdshack-urbanbot-dev-register-consent"
    error_message = "register_consent must use the cdshack-urbanbot naming convention."
  }

  assert {
    condition     = aws_lambda_function.register_consent.environment[0].variables["USERS_TABLE"] == "users"
    error_message = "register_consent must write the users table."
  }

  assert {
    condition     = aws_lambda_function.agent.environment[0].variables["TOOL_REGISTER_CONSENT_FN"] == "cdshack-urbanbot-dev-register-consent"
    error_message = "The agent must invoke the register_consent tool Lambda."
  }

  assert {
    condition     = aws_iam_role.register_consent.name == "cdshack-urbanbot-dev-register-consent-role"
    error_message = "register_consent must run under its own least-privilege role."
  }
}
