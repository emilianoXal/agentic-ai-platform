variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "prod"
}


variable "media_retention_days" {
  description = "Number of days before objects under the \"raw/\" prefix in the media bucket expire."
  type        = number
  default     = 30
}

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

# =============================================================================
# Agent module — feature flags + tunables.
# =============================================================================
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

variable "routing_rules_json" {
  description = "JSON map category -> {dependency, channel} used by the route tool."
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
  description = "Maximum number of places a user may register."
  type        = number
  default     = 3
}

variable "default_place_radius_m" {
  description = "Default radius (meters) stored on a place when none is provided."
  type        = number
  default     = 500
}

variable "recent_window_hours" {
  description = "Clustering recency window (hours) for attaching reports to an active OPEN incident."
  type        = number
  default     = 72
}

variable "bedrock_model_id" {
  description = "Bare Bedrock foundation-model id (NOT a us.* inference-profile id)."
  type        = string
  default     = "anthropic.claude-3-5-sonnet-20241022-v2:0"
}

# =============================================================================
# Portal module — dashboard staff accounts.
# =============================================================================
variable "staff_users" {
  description = "Dashboard staff: email -> { name, group (agency | official | admin), agency_id }."
  type = map(object({
    name      = string
    group     = string
    agency_id = optional(string)
  }))
  default = {}
}
