output "user_pool_id" {
  description = "Cognito user pool for dashboard staff."
  value       = aws_cognito_user_pool.staff.id
}

output "user_pool_client_id" {
  description = "Public (no secret) app client the dashboard signs in with."
  value       = aws_cognito_user_pool_client.dashboard.id
}

output "graphql_url" {
  description = "AppSync GraphQL endpoint."
  value       = aws_appsync_graphql_api.this.uris["GRAPHQL"]
}

output "graphql_api_id" {
  description = "AppSync API id."
  value       = aws_appsync_graphql_api.this.id
}

output "maps_api_key_name" {
  description = "Amazon Location API key name; the deploy job reads its value with location:DescribeKey."
  value       = awscc_location_api_key.maps.key_name
}

output "dashboard_app_id" {
  description = "Amplify Hosting app id (the deploy job uploads the build zip to it)."
  value       = var.enable_hosting ? aws_amplify_app.dashboard[0].id : null
}

output "dashboard_branch_name" {
  description = "Amplify branch that receives the deployments."
  value       = var.enable_hosting ? aws_amplify_branch.main[0].branch_name : null
}

output "dashboard_url" {
  description = "Public URL of the dashboard."
  value       = local.dashboard_origin
}

output "dashboard_api_function_name" {
  description = "Name of the dashboard API Lambda."
  value       = aws_lambda_function.dashboard_api.function_name
}
