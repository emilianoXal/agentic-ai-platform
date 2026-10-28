mock_provider "aws" {
  mock_resource "aws_iam_role" {
    defaults = {
      arn = "arn:aws:iam::123456789012:role/cdshack-follow-up-role"
    }
  }
  mock_resource "aws_iam_policy" {
    defaults = {
      arn = "arn:aws:iam::123456789012:policy/cdshack-follow-up-policy"
    }
  }
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
  mock_resource "aws_lambda_function" {
    defaults = {
      arn = "arn:aws:lambda:us-east-1:123456789012:function:cdshack-urbanbot-dev-follow-up"
    }
  }
}

variables {
  environment                          = "dev"
  incidents_table_name                 = "incidents"
  incidents_table_arn                  = "arn:aws:dynamodb:us-east-1:123456789012:table/incidents"
  reports_table_name                   = "reports"
  reports_table_arn                    = "arn:aws:dynamodb:us-east-1:123456789012:table/reports"
  users_table_name                     = "users"
  users_table_arn                      = "arn:aws:dynamodb:us-east-1:123456789012:table/users"
  audit_log_table_name                 = "audit"
  audit_log_table_arn                  = "arn:aws:dynamodb:us-east-1:123456789012:table/audit"
  kms_key_arn                          = "arn:aws:kms:us-east-1:123456789012:key/00000000-0000-0000-0000-000000000000"
  outbound_function_name               = "outbound"
  outbound_function_arn                = "arn:aws:lambda:us-east-1:123456789012:function:outbound"
  outbound_origination_phone_number_id = "phone-number-id-test"
}

run "scheduler_can_only_invoke_follow_up" {
  command = apply

  assert {
    condition = (
      length(jsondecode(aws_iam_policy.scheduler.policy).Statement) == 1 &&
      jsondecode(aws_iam_policy.scheduler.policy).Statement[0].Effect == "Allow" &&
      jsondecode(aws_iam_policy.scheduler.policy).Statement[0].Action == ["lambda:InvokeFunction"] &&
      jsondecode(aws_iam_policy.scheduler.policy).Statement[0].Resource == [aws_lambda_function.follow_up.arn]
    )
    error_message = "The Scheduler execution role must invoke only the follow-up Lambda."
  }

  assert {
    condition = (
      aws_lambda_function.follow_up.environment[0].variables.OUTBOUND_FUNCTION_NAME == var.outbound_function_name &&
      aws_lambda_function.follow_up.environment[0].variables.INCIDENTS_TABLE == var.incidents_table_name &&
      aws_lambda_function.follow_up.environment[0].variables.REPORTS_TABLE == var.reports_table_name &&
      aws_lambda_function.follow_up.environment[0].variables.OUTBOUND_ORIGINATION_PHONE_NUMBER_ID == var.outbound_origination_phone_number_id
    )
    error_message = "Follow-up must use the existing outbound sender and incident/report data."
  }
}
