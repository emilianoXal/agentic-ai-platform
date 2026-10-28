provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = {
      Project     = "cdshack-urbanbot"
      Agente      = "urbanbot"
      Environment = var.environment
      ManagedBy   = "terraform"
      Repo        = "hackaton-aws-cds-agentic-ai/agentic-ai-platform"
      Owner       = "xaldigital"
    }
  }
}

provider "awscc" {
  region = "us-east-1"
}

module "data" {
  source = "../../modules/data"

  environment          = var.environment
  media_retention_days = var.media_retention_days
}

module "compute" {
  source = "../../modules/compute"

  environment              = var.environment
  permissions_boundary_arn = var.permissions_boundary_arn

  kms_key_arn       = module.data.kms_key_arn
  ingest_queue_url  = module.data.ingest_queue_url
  ingest_queue_arn  = module.data.ingest_queue_arn
  inbound_topic_arn = module.data.inbound_topic_arn
  event_bus_name    = module.data.events_bus_name
  event_bus_arn     = module.data.events_bus_arn
  users_table_name  = module.data.users_table_name
  users_table_arn   = module.data.users_table_arn
  places_table_name = module.data.places_table_name
  places_table_arn  = module.data.places_table_arn
  audit_table_name  = module.data.audit_log_table_name
  audit_table_arn   = module.data.audit_log_table_arn

  rate_limit_per_hour = var.rate_limit_per_hour
  max_text_len        = var.max_text_len
  daily_cap_default   = var.daily_cap_default
  log_retention_days  = var.log_retention_days
  log_level           = var.log_level
}

module "agent" {
  source = "../../modules/agent"

  environment              = var.environment
  permissions_boundary_arn = var.permissions_boundary_arn

  enable_agentcore_runtime = var.enable_agentcore_runtime
  enable_agentcore_gateway = var.enable_agentcore_gateway
  enable_agentcore_memory  = var.enable_agentcore_memory

  kms_key_arn          = module.data.kms_key_arn
  reports_table_name   = module.data.reports_table_name
  reports_table_arn    = module.data.reports_table_arn
  incidents_table_name = module.data.incidents_table_name
  incidents_table_arn  = module.data.incidents_table_arn
  places_table_name    = module.data.places_table_name
  places_table_arn     = module.data.places_table_arn
  users_table_name     = module.data.users_table_name
  users_table_arn      = module.data.users_table_arn
  audit_log_table_name = module.data.audit_log_table_name
  audit_log_table_arn  = module.data.audit_log_table_arn
  ingest_queue_arn     = module.data.ingest_queue_arn
  ingest_queue_url     = module.data.ingest_queue_url
  events_bus_name      = module.data.events_bus_name
  events_bus_arn       = module.data.events_bus_arn

  routing_rules_json        = var.routing_rules_json
  escalate_report_threshold = var.escalate_report_threshold
  escalate_days_threshold   = var.escalate_days_threshold
  max_places_per_user       = var.max_places_per_user
  default_place_radius_m    = var.default_place_radius_m
  recent_window_hours       = var.recent_window_hours
  log_retention_days        = var.log_retention_days
  log_level                 = var.log_level
  bedrock_model_id          = var.bedrock_model_id
}
