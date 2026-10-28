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

run "one_sqs_delivery_drives_one_agent_turn_at_a_time" {
  command = plan

  assert {
    condition = (
      tonumber(aws_lambda_function.consumer.environment[0].variables.AGENT_INVOKE_READ_TIMEOUT) > aws_lambda_function.agent.timeout
    )
    error_message = "The consumer must wait for the agent longer than the agent timeout."
  }

  assert {
    condition = (
      aws_lambda_event_source_mapping.consumer.batch_size
      * tonumber(aws_lambda_function.consumer.environment[0].variables.AGENT_INVOKE_READ_TIMEOUT)
      < aws_lambda_function.consumer.timeout
    )
    error_message = "A full batch of serial agent invocations must fit in the consumer timeout."
  }

  assert {
    condition     = var.ingest_queue_visibility_timeout_seconds >= 6 * aws_lambda_function.consumer.timeout
    error_message = "The ingest queue must stay invisible for at least six consumer timeouts."
  }
}

run "short_queue_visibility_is_rejected" {
  command = plan

  variables {
    ingest_queue_visibility_timeout_seconds = 30
  }

  expect_failures = [aws_lambda_event_source_mapping.consumer]
}
