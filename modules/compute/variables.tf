variable "environment" {
  description = "Deployment environment (dev | qa | prod)."
  type        = string
}

# =============================================================================
# Data-module values (passed in from the env; no module.data reach-in here).
# =============================================================================
variable "kms_key_arn" {
  description = "ARN of the data-encryption CMK the Lambdas use for Decrypt/GenerateDataKey."
  type        = string
}

variable "ingest_queue_url" {
  description = "URL of the FIFO ingest queue the ingest Lambda sends normalized messages to."
  type        = string
}

variable "ingest_queue_arn" {
  description = "ARN of the FIFO ingest queue (scoped target of the ingest sqs:SendMessage grant)."
  type        = string
}

variable "inbound_topic_arn" {
  description = "ARN of the inbound SNS topic the ingest Lambda subscribes to."
  type        = string
}

variable "event_bus_name" {
  description = "Name of the custom EventBridge bus the notifier rule listens on (maps to data events_bus_name)."
  type        = string
}

variable "event_bus_arn" {
  description = "ARN of the custom EventBridge bus (maps to data events_bus_arn)."
  type        = string
}

variable "users_table_name" {
  description = "Name of the users DynamoDB table."
  type        = string
}

variable "users_table_arn" {
  description = "ARN of the users DynamoDB table."
  type        = string
}

variable "places_table_name" {
  description = "Name of the places DynamoDB table."
  type        = string
}

variable "places_table_arn" {
  description = "ARN of the places DynamoDB table."
  type        = string
}

variable "audit_table_name" {
  description = "Name of the audit-log DynamoDB table (maps to data audit_log_table_name)."
  type        = string
}

variable "audit_table_arn" {
  description = "ARN of the audit-log DynamoDB table (maps to data audit_log_table_arn)."
  type        = string
}

variable "incidents_table_name" {
  description = "Name of the incidents DynamoDB table used to enrich dependency e-mails."
  type        = string
}

variable "incidents_table_arn" {
  description = "ARN of the incidents DynamoDB table."
  type        = string
}

variable "dependency_email_map" {
  description = "Incident category to responsible agency e-mail address."
  type        = map(string)
  default     = {}
}

variable "dependency_fallback_email" {
  description = "Recipient used when an incident category has no explicit agency address."
  type        = string
  default     = "antonio.miguel+supervisor@xaldigital.com"
}

variable "portal_url" {
  description = "Dashboard origin linked from dependency e-mails; null keeps the dev Amplify origin."
  type        = string
  default     = "https://main.d1taemvhj3go47.amplifyapp.com"
  nullable    = false
}

variable "dependency_mail_from" {
  description = "Verified SES identity used as the dependency notice sender."
  type        = string
  default     = "antonio.miguel@xaldigital.com"
}

# =============================================================================
# Tunables.
# =============================================================================
variable "rate_limit_per_hour" {
  description = "Per-user inbound message rate limit per hour before messages are annotated rate_limited."
  type        = number
  default     = 60
}

variable "max_text_len" {
  description = "Maximum inbound text length before truncation (input guard)."
  type        = number
  default     = 4096
}

variable "daily_cap_default" {
  description = "Default per-user daily notification cap when the user has no explicit daily_cap."
  type        = number
  default     = 10
}

variable "log_retention_days" {
  description = "CloudWatch log retention (days) for both Lambda log groups."
  type        = number
  default     = 14
}

variable "log_level" {
  description = "Log level passed to the Lambda handlers (DEBUG | INFO | WARNING | ERROR)."
  type        = string
  default     = "INFO"
}
