output "follow_up_function_name" {
  value = aws_lambda_function.follow_up.function_name
}
output "follow_up_function_arn" {
  value = aws_lambda_function.follow_up.arn
}
output "follow_up_scheduler_role_arn" {
  value      = aws_iam_role.scheduler.arn
  depends_on = [aws_iam_role_policy_attachment.scheduler]
}
