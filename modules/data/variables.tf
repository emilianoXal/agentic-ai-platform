variable "environment" {
  description = "Deployment environment (dev | qa | prod). Used to derive the resource name prefix and tags."
  type        = string
}

variable "media_retention_days" {
  description = "Number of days before objects under the \"raw/\" prefix in the media bucket expire."
  type        = number
  default     = 30
}
