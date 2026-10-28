# =============================================================================
# Identity / feature flags.
# =============================================================================
variable "environment" {
  description = "Deployment environment (dev | qa | prod)."
  type        = string
}

variable "enable_agentcore_gateway" {
  description = "Create the AgentCore Gateway (awscc). Default false."
  type        = bool
  default     = false
}

variable "enable_agentcore_memory" {
  description = "Create the AgentCore Memory (awscc). Default false."
  type        = bool
  default     = false
}

# =============================================================================
# Data-module values (passed in from the env; no module.data reach-in here).
# Kept at the data module's real output names (1:1 pass-through, no rename).
# =============================================================================
variable "kms_key_arn" {
  description = "ARN of the data-encryption CMK the Lambdas use for Decrypt/GenerateDataKey."
  type        = string
}

variable "reports_table_name" {
  description = "Name of the reports DynamoDB table."
  type        = string
}

variable "reports_table_arn" {
  description = "ARN of the reports DynamoDB table."
  type        = string
}

variable "incidents_table_name" {
  description = "Name of the incidents DynamoDB table."
  type        = string
}

variable "incidents_table_arn" {
  description = "ARN of the incidents DynamoDB table."
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

variable "users_table_name" {
  description = "Name of the users DynamoDB table."
  type        = string
}

variable "users_table_arn" {
  description = "ARN of the users DynamoDB table."
  type        = string
}

variable "audit_log_table_name" {
  description = "Name of the audit-log DynamoDB table."
  type        = string
}

variable "audit_log_table_arn" {
  description = "ARN of the audit-log DynamoDB table."
  type        = string
}

variable "ingest_queue_arn" {
  description = "ARN of the FIFO ingest queue the consumer Lambda drains."
  type        = string
}

variable "ingest_queue_url" {
  description = "URL of the FIFO ingest queue."
  type        = string
}

variable "events_bus_name" {
  description = "Name of the custom EventBridge bus the route/escalate tools publish to."
  type        = string
}

variable "events_bus_arn" {
  description = "ARN of the custom EventBridge bus (scoped target of events:PutEvents)."
  type        = string
}

variable "outbound_function_name" {
  description = "Name of the outbound WhatsApp send Lambda the consumer invokes."
  type        = string
}

variable "outbound_function_arn" {
  description = "ARN of the outbound Lambda - scoped target of the consumer lambda:InvokeFunction grant."
  type        = string
}

# =============================================================================
# Config / tunables.
# =============================================================================
variable "routing_rules_json" {
  description = "JSON map category -> {dependency, channel} used by the route tool. Default empty object (falls back to built-in defaults)."
  type        = string
  default     = "{}"
}

variable "escalate_report_threshold" {
  description = "Report-count at/above which an incident may be escalated."
  type        = number
  default     = 10
}

variable "escalate_days_threshold" {
  description = "Age-in-days at/above which an OPEN incident may be escalated."
  type        = number
  default     = 3
}

variable "max_places_per_user" {
  description = "Maximum number of places a user may register (RF-23)."
  type        = number
  default     = 3
}

variable "default_place_radius_m" {
  description = "Default radius (meters) stored on a place when none is provided."
  type        = number
  default     = 500
}

variable "recent_window_hours" {
  description = "Clustering recency window (hours) for attaching reports to an active OPEN incident (RF-29)."
  type        = number
  default     = 72
}

variable "log_retention_days" {
  description = "CloudWatch log retention (days) for the Lambda log groups."
  type        = number
  default     = 14
}

variable "log_level" {
  description = "Log level passed to the Lambda handlers (DEBUG | INFO | WARNING | ERROR)."
  type        = string
  default     = "INFO"
}

variable "bedrock_model_id" {
  description = "Bare Bedrock foundation-model id (NOT a us.* inference-profile id); the exec-role derives the profile ARN from it."
  type        = string
  default     = "anthropic.claude-sonnet-5-5"
}
