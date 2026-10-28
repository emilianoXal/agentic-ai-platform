# =============================================================================
# Identity.
# =============================================================================
variable "environment" {
  description = "Deployment environment (dev | qa | prod)."
  type        = string
}

# =============================================================================
# Data-module values (passed in from the env, real output names 1:1).
# =============================================================================
variable "kms_key_arn" {
  description = "ARN of the data-encryption CMK (tables and streams are encrypted with it)."
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

variable "incidents_stream_arn" {
  description = "Stream ARN of the incidents DynamoDB table (feeds the real-time dashboard)."
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

variable "audit_log_table_name" {
  description = "Name of the audit-log DynamoDB table."
  type        = string
}

variable "audit_log_table_arn" {
  description = "ARN of the audit-log DynamoDB table."
  type        = string
}

variable "users_table_name" {
  description = "Name of the users DynamoDB table (demo seed writes synthetic users)."
  type        = string
}

variable "users_table_arn" {
  description = "ARN of the users DynamoDB table."
  type        = string
}

variable "events_bus_name" {
  description = "Name of the EventBridge bus the notifier listens on."
  type        = string
}

variable "events_bus_arn" {
  description = "ARN of the EventBridge bus the notifier listens on."
  type        = string
}

# =============================================================================
# Tunables.
# =============================================================================
variable "routing_rules_json" {
  description = "Same JSON routing map the route tool uses; the dashboard lists its agencies."
  type        = string
  default     = "{}"
}

variable "follow_up_hours" {
  description = "Hours after Resolved before neighbors are asked \"Is it fixed?\" (RF-20)."
  type        = number
  default     = 24
}

variable "local_dev_origins" {
  description = "Extra origins allowed to use the maps API key (local development)."
  type        = list(string)
  default     = ["http://localhost:4200", "http://localhost:4300"]
}

variable "enable_hosting" {
  description = "Create the Amplify Hosting app for the dashboard."
  type        = bool
  default     = true
}

variable "staff_users" {
  description = "Dashboard staff accounts: email -> { name, group (agency | official | admin), agency_id (agency only) }. Cognito e-mails each a temporary password."
  type = map(object({
    name      = string
    group     = string
    agency_id = optional(string)
  }))
  default = {}

  validation {
    condition     = alltrue([for u in values(var.staff_users) : contains(["agency", "official", "admin"], u.group)])
    error_message = "Each staff user group must be agency, official or admin."
  }

  validation {
    condition     = alltrue([for u in values(var.staff_users) : u.group != "agency" || try(length(u.agency_id) > 0, false)])
    error_message = "Agency operators need an agency_id (e.g. organismo-de-agua)."
  }
}

variable "user_pool_deletion_protection" {
  description = "Protect the staff user pool from deletion (ACTIVE in prod)."
  type        = string
  default     = "INACTIVE"
}

variable "log_retention_days" {
  description = "CloudWatch log retention (days)."
  type        = number
  default     = 14
}

variable "log_level" {
  description = "Log level for the Lambda handlers (DEBUG | INFO | WARNING | ERROR)."
  type        = string
  default     = "INFO"
}
