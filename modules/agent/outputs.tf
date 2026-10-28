# =============================================================================
# Tool Lambdas — function names + ARNs.
# =============================================================================
output "create_report_function_name" {
  description = "Name of the create_report tool Lambda."
  value       = aws_lambda_function.create_report.function_name
}

output "create_report_function_arn" {
  description = "ARN of the create_report tool Lambda."
  value       = aws_lambda_function.create_report.arn
}

output "join_incident_function_name" {
  description = "Name of the join_incident tool Lambda."
  value       = aws_lambda_function.join_incident.function_name
}

output "join_incident_function_arn" {
  description = "ARN of the join_incident tool Lambda."
  value       = aws_lambda_function.join_incident.arn
}

output "get_status_function_name" {
  description = "Name of the get_status tool Lambda."
  value       = aws_lambda_function.get_status.function_name
}

output "get_status_function_arn" {
  description = "ARN of the get_status tool Lambda."
  value       = aws_lambda_function.get_status.arn
}

output "register_place_function_name" {
  description = "Name of the register_place tool Lambda."
  value       = aws_lambda_function.register_place.function_name
}

output "register_place_function_arn" {
  description = "ARN of the register_place tool Lambda."
  value       = aws_lambda_function.register_place.arn
}

output "delete_my_data_function_name" {
  description = "Name of the delete_my_data tool Lambda."
  value       = aws_lambda_function.delete_my_data.function_name
}

output "delete_my_data_function_arn" {
  description = "ARN of the delete_my_data tool Lambda."
  value       = aws_lambda_function.delete_my_data.arn
}

output "route_function_name" {
  description = "Name of the route tool Lambda."
  value       = aws_lambda_function.route.function_name
}

output "route_function_arn" {
  description = "ARN of the route tool Lambda."
  value       = aws_lambda_function.route.arn
}

output "escalate_function_name" {
  description = "Name of the escalate tool Lambda."
  value       = aws_lambda_function.escalate.function_name
}

output "escalate_function_arn" {
  description = "ARN of the escalate tool Lambda."
  value       = aws_lambda_function.escalate.arn
}

# =============================================================================
# Consumer Lambda.
# =============================================================================
output "consumer_function_name" {
  description = "Name of the SQS consumer Lambda."
  value       = aws_lambda_function.consumer.function_name
}

output "consumer_function_arn" {
  description = "ARN of the SQS consumer Lambda."
  value       = aws_lambda_function.consumer.arn
}

# =============================================================================
# Agent Lambda + Strands layer.
# =============================================================================
output "agent_function_name" {
  description = "Name of the Strands agent Lambda."
  value       = aws_lambda_function.agent.function_name
}

output "agent_function_arn" {
  description = "ARN of the Strands agent Lambda."
  value       = aws_lambda_function.agent.arn
}

output "agent_role_arn" {
  description = "ARN of the Strands agent Lambda execution role."
  value       = aws_iam_role.agent.arn
}

output "strands_layer_arn" {
  description = "ARN of the published Strands Lambda layer version."
  value       = aws_lambda_layer_version.strands.arn
}

# =============================================================================
# Bedrock Guardrail.
# =============================================================================
output "guardrail_id" {
  description = "Id of the Bedrock Guardrail."
  value       = aws_bedrock_guardrail.this.guardrail_id
}

output "guardrail_version" {
  description = "Published version of the Bedrock Guardrail."
  value       = aws_bedrock_guardrail_version.this.version
}

# =============================================================================
# AgentCore.
# =============================================================================
output "agentcore_exec_role_arn" {
  description = "ARN of the AgentCore execution role (created regardless of the flags)."
  value       = aws_iam_role.agentcore_exec.arn
}

output "agentcore_gateway_id" {
  description = "Id of the AgentCore Gateway (null when enable_agentcore_gateway is false)."
  value       = one(awscc_bedrockagentcore_gateway.this[*].gateway_identifier)
}

output "agentcore_memory_id" {
  description = "Id of the AgentCore Memory (null when enable_agentcore_memory is false)."
  value       = one(awscc_bedrockagentcore_memory.this[*].memory_id)
}
