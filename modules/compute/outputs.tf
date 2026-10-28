output "ingest_function_name" {
  description = "Name of the ingest Lambda function."
  value       = aws_lambda_function.ingest.function_name
}

output "ingest_function_arn" {
  description = "ARN of the ingest Lambda function."
  value       = aws_lambda_function.ingest.arn
}

output "notifier_function_name" {
  description = "Name of the notifier Lambda function."
  value       = aws_lambda_function.notifier.function_name
}

output "notifier_function_arn" {
  description = "ARN of the notifier Lambda function."
  value       = aws_lambda_function.notifier.arn
}

output "ingest_role_arn" {
  description = "ARN of the ingest Lambda execution role."
  value       = aws_iam_role.ingest.arn
}

output "notifier_role_arn" {
  description = "ARN of the notifier Lambda execution role."
  value       = aws_iam_role.notifier.arn
}

output "outbound_function_name" {
  description = "Name of the outbound WhatsApp send Lambda function."
  value       = aws_lambda_function.outbound.function_name
}

output "outbound_function_arn" {
  description = "ARN of the outbound WhatsApp send Lambda function."
  value       = aws_lambda_function.outbound.arn
}

output "outbound_role_arn" {
  description = "ARN of the outbound Lambda execution role."
  value       = aws_iam_role.outbound.arn
}

output "media_state_machine_arn" {
  description = "ARN of the WhatsApp image sanitization state machine."
  value       = aws_sfn_state_machine.media.arn
}
