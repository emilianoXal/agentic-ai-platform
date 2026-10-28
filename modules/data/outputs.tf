# =============================================================================
# KMS
# =============================================================================
output "kms_key_arn" {
  description = "ARN of the data-encryption CMK."
  value       = aws_kms_key.this.arn
}

output "kms_key_alias" {
  description = "Alias of the data-encryption CMK."
  value       = aws_kms_alias.this.name
}

# =============================================================================
# S3
# =============================================================================
output "media_bucket_name" {
  description = "Name of the media S3 bucket."
  value       = aws_s3_bucket.media.id
}

output "media_bucket_arn" {
  description = "ARN of the media S3 bucket."
  value       = aws_s3_bucket.media.arn
}

# =============================================================================
# DynamoDB
# =============================================================================
output "reports_table_name" {
  description = "Name of the reports DynamoDB table."
  value       = aws_dynamodb_table.reports.name
}

output "reports_table_arn" {
  description = "ARN of the reports DynamoDB table."
  value       = aws_dynamodb_table.reports.arn
}

output "reports_stream_arn" {
  description = "Stream ARN of the reports DynamoDB table."
  value       = aws_dynamodb_table.reports.stream_arn
}

output "incidents_table_name" {
  description = "Name of the incidents DynamoDB table."
  value       = aws_dynamodb_table.incidents.name
}

output "incidents_table_arn" {
  description = "ARN of the incidents DynamoDB table."
  value       = aws_dynamodb_table.incidents.arn
}

output "incidents_stream_arn" {
  description = "Stream ARN of the incidents DynamoDB table."
  value       = aws_dynamodb_table.incidents.stream_arn
}

output "places_table_name" {
  description = "Name of the places DynamoDB table."
  value       = aws_dynamodb_table.places.name
}

output "places_table_arn" {
  description = "ARN of the places DynamoDB table."
  value       = aws_dynamodb_table.places.arn
}

output "users_table_name" {
  description = "Name of the users DynamoDB table."
  value       = aws_dynamodb_table.users.name
}

output "users_table_arn" {
  description = "ARN of the users DynamoDB table."
  value       = aws_dynamodb_table.users.arn
}

output "audit_log_table_name" {
  description = "Name of the audit-log DynamoDB table."
  value       = aws_dynamodb_table.audit_log.name
}

output "audit_log_table_arn" {
  description = "ARN of the audit-log DynamoDB table."
  value       = aws_dynamodb_table.audit_log.arn
}

# =============================================================================
# SNS
# =============================================================================
output "inbound_topic_arn" {
  description = "ARN of the inbound SNS topic."
  value       = aws_sns_topic.inbound.arn
}

# =============================================================================
# SQS
# =============================================================================
output "ingest_queue_arn" {
  description = "ARN of the FIFO ingest queue."
  value       = aws_sqs_queue.ingest.arn
}

output "ingest_queue_visibility_timeout_seconds" {
  description = "Visibility timeout (seconds) of the FIFO ingest queue."
  value       = aws_sqs_queue.ingest.visibility_timeout_seconds
}

output "ingest_queue_url" {
  description = "URL of the FIFO ingest queue."
  value       = aws_sqs_queue.ingest.url
}

output "ingest_dlq_arn" {
  description = "ARN of the FIFO ingest dead-letter queue."
  value       = aws_sqs_queue.ingest_dlq.arn
}

output "ingest_dlq_url" {
  description = "URL of the FIFO ingest dead-letter queue."
  value       = aws_sqs_queue.ingest_dlq.url
}

# =============================================================================
# EventBridge
# =============================================================================
output "events_bus_arn" {
  description = "ARN of the custom EventBridge bus."
  value       = aws_cloudwatch_event_bus.events.arn
}

output "events_bus_name" {
  description = "Name of the custom EventBridge bus."
  value       = aws_cloudwatch_event_bus.events.name
}
