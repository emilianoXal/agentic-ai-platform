output "kms_key_arn" {
  description = "ARN of the data-encryption CMK."
  value       = module.data.kms_key_arn
}

output "kms_key_alias" {
  description = "Alias of the data-encryption CMK."
  value       = module.data.kms_key_alias
}

output "media_bucket_name" {
  description = "Name of the media S3 bucket."
  value       = module.data.media_bucket_name
}

output "media_bucket_arn" {
  description = "ARN of the media S3 bucket."
  value       = module.data.media_bucket_arn
}

output "reports_table_name" {
  description = "Name of the reports DynamoDB table."
  value       = module.data.reports_table_name
}

output "reports_table_arn" {
  description = "ARN of the reports DynamoDB table."
  value       = module.data.reports_table_arn
}

output "reports_stream_arn" {
  description = "Stream ARN of the reports DynamoDB table."
  value       = module.data.reports_stream_arn
}

output "incidents_table_name" {
  description = "Name of the incidents DynamoDB table."
  value       = module.data.incidents_table_name
}

output "incidents_table_arn" {
  description = "ARN of the incidents DynamoDB table."
  value       = module.data.incidents_table_arn
}

output "incidents_stream_arn" {
  description = "Stream ARN of the incidents DynamoDB table."
  value       = module.data.incidents_stream_arn
}

output "places_table_name" {
  description = "Name of the places DynamoDB table."
  value       = module.data.places_table_name
}

output "places_table_arn" {
  description = "ARN of the places DynamoDB table."
  value       = module.data.places_table_arn
}

output "users_table_name" {
  description = "Name of the users DynamoDB table."
  value       = module.data.users_table_name
}

output "users_table_arn" {
  description = "ARN of the users DynamoDB table."
  value       = module.data.users_table_arn
}

output "audit_log_table_name" {
  description = "Name of the audit-log DynamoDB table."
  value       = module.data.audit_log_table_name
}

output "audit_log_table_arn" {
  description = "ARN of the audit-log DynamoDB table."
  value       = module.data.audit_log_table_arn
}

output "inbound_topic_arn" {
  description = "ARN of the inbound SNS topic."
  value       = module.data.inbound_topic_arn
}

output "ingest_queue_arn" {
  description = "ARN of the FIFO ingest queue."
  value       = module.data.ingest_queue_arn
}

output "ingest_queue_url" {
  description = "URL of the FIFO ingest queue."
  value       = module.data.ingest_queue_url
}

output "ingest_dlq_arn" {
  description = "ARN of the FIFO ingest dead-letter queue."
  value       = module.data.ingest_dlq_arn
}

output "ingest_dlq_url" {
  description = "URL of the FIFO ingest dead-letter queue."
  value       = module.data.ingest_dlq_url
}

output "events_bus_arn" {
  description = "ARN of the custom EventBridge bus."
  value       = module.data.events_bus_arn
}

output "events_bus_name" {
  description = "Name of the custom EventBridge bus."
  value       = module.data.events_bus_name
}

# =============================================================================
# Compute
# =============================================================================
output "ingest_function_name" {
  description = "Name of the ingest Lambda function."
  value       = module.compute.ingest_function_name
}

output "ingest_function_arn" {
  description = "ARN of the ingest Lambda function."
  value       = module.compute.ingest_function_arn
}

output "notifier_function_name" {
  description = "Name of the notifier Lambda function."
  value       = module.compute.notifier_function_name
}

output "notifier_function_arn" {
  description = "ARN of the notifier Lambda function."
  value       = module.compute.notifier_function_arn
}

output "ingest_role_arn" {
  description = "ARN of the ingest Lambda execution role."
  value       = module.compute.ingest_role_arn
}

output "notifier_role_arn" {
  description = "ARN of the notifier Lambda execution role."
  value       = module.compute.notifier_role_arn
}

# =============================================================================
# Agent
# =============================================================================
output "create_report_function_arn" {
  description = "ARN of the create_report tool Lambda."
  value       = module.agent.create_report_function_arn
}

output "join_incident_function_arn" {
  description = "ARN of the join_incident tool Lambda."
  value       = module.agent.join_incident_function_arn
}

output "get_status_function_arn" {
  description = "ARN of the get_status tool Lambda."
  value       = module.agent.get_status_function_arn
}

output "register_place_function_arn" {
  description = "ARN of the register_place tool Lambda."
  value       = module.agent.register_place_function_arn
}

output "route_function_arn" {
  description = "ARN of the route tool Lambda."
  value       = module.agent.route_function_arn
}

output "escalate_function_arn" {
  description = "ARN of the escalate tool Lambda."
  value       = module.agent.escalate_function_arn
}

output "consumer_function_arn" {
  description = "ARN of the SQS consumer Lambda."
  value       = module.agent.consumer_function_arn
}

output "agent_ecr_repository_url" {
  description = "URL of the ECR repository for the Strands agent image."
  value       = module.agent.ecr_repository_url
}

output "agent_guardrail_id" {
  description = "Id of the Bedrock Guardrail."
  value       = module.agent.guardrail_id
}

output "agent_guardrail_version" {
  description = "Published version of the Bedrock Guardrail."
  value       = module.agent.guardrail_version
}

output "agentcore_exec_role_arn" {
  description = "ARN of the AgentCore execution role."
  value       = module.agent.agentcore_exec_role_arn
}

output "agentcore_runtime_id" {
  description = "Id of the AgentCore Runtime (null when disabled)."
  value       = module.agent.agentcore_runtime_id
}

output "agentcore_gateway_id" {
  description = "Id of the AgentCore Gateway (null when disabled)."
  value       = module.agent.agentcore_gateway_id
}

output "agentcore_memory_id" {
  description = "Id of the AgentCore Memory (null when disabled)."
  value       = module.agent.agentcore_memory_id
}

# =============================================================================
# Portal (dashboard) — consumed by the dashboard deploy job to build config.json.
# =============================================================================
output "portal_user_pool_id" {
  description = "Cognito user pool for dashboard staff."
  value       = module.portal.user_pool_id
}

output "portal_user_pool_client_id" {
  description = "Cognito app client for the dashboard."
  value       = module.portal.user_pool_client_id
}

output "portal_graphql_url" {
  description = "AppSync GraphQL endpoint of the dashboard API."
  value       = module.portal.graphql_url
}

output "portal_maps_api_key_name" {
  description = "Amazon Location API key name for the dashboard map."
  value       = module.portal.maps_api_key_name
}

output "portal_dashboard_app_id" {
  description = "Amplify Hosting app of the dashboard."
  value       = module.portal.dashboard_app_id
}

output "portal_dashboard_branch_name" {
  description = "Amplify branch that receives dashboard deployments."
  value       = module.portal.dashboard_branch_name
}

output "portal_dashboard_url" {
  description = "Public URL of the dashboard."
  value       = module.portal.dashboard_url
}
