variable "environment" {
  description = "Deployment environment (dev | qa | prod). Used to derive the resource name prefix and tags."
  type        = string
}

variable "media_retention_days" {
  description = "Number of days before objects under the \"raw/\" prefix in the media bucket expire."
  type        = number
  default     = 1
}

variable "sanitized_media_retention_days" {
  description = "Number of days before sanitized media objects expire."
  type        = number
  default     = 30
}

variable "enable_conversation_history" {
  description = "Create the DynamoDB conversation-history table. Default false."
  type        = bool
  default     = false
}
