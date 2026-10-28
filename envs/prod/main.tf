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

  environment                    = var.environment
  media_retention_days           = var.media_retention_days
  sanitized_media_retention_days = var.sanitized_media_retention_days
  enable_conversation_history    = var.enable_conversation_history
}

module "compute" {
  source = "../../modules/compute"

  environment = var.environment

  kms_key_arn              = module.data.kms_key_arn
  ingest_queue_url         = module.data.ingest_queue_url
  ingest_queue_arn         = module.data.ingest_queue_arn
  inbound_topic_arn        = module.data.inbound_topic_arn
  media_bucket_name        = module.data.media_bucket_name
  media_bucket_arn         = module.data.media_bucket_arn
  event_bus_name           = module.data.events_bus_name
  event_bus_arn            = module.data.events_bus_arn
  users_table_name         = module.data.users_table_name
  users_table_arn          = module.data.users_table_arn
  pending_media_table_name = module.data.pending_media_table_name
  pending_media_table_arn  = module.data.pending_media_table_arn
  places_table_name        = module.data.places_table_name
  places_table_arn         = module.data.places_table_arn
  audit_table_name         = module.data.audit_log_table_name
  audit_table_arn          = module.data.audit_log_table_arn
  incidents_table_name     = module.data.incidents_table_name
  incidents_table_arn      = module.data.incidents_table_arn

  dependency_email_map      = var.dependency_email_map
  dependency_fallback_email = var.dependency_fallback_email
  dependency_mail_from      = var.dependency_mail_from
  portal_url                = module.portal.dashboard_url

  rate_limit_per_hour                  = var.rate_limit_per_hour
  max_text_len                         = var.max_text_len
  daily_cap_default                    = var.daily_cap_default
  log_retention_days                   = var.log_retention_days
  log_level                            = var.log_level
  meta_api_version                     = var.meta_api_version
  outbound_origination_phone_number_id = var.outbound_origination_phone_number_id
}

module "follow_up" {
  source                               = "../../modules/follow_up"
  environment                          = var.environment
  kms_key_arn                          = module.data.kms_key_arn
  incidents_table_name                 = module.data.incidents_table_name
  incidents_table_arn                  = module.data.incidents_table_arn
  reports_table_name                   = module.data.reports_table_name
  reports_table_arn                    = module.data.reports_table_arn
  users_table_name                     = module.data.users_table_name
  users_table_arn                      = module.data.users_table_arn
  audit_log_table_name                 = module.data.audit_log_table_name
  audit_log_table_arn                  = module.data.audit_log_table_arn
  outbound_function_name               = module.compute.outbound_function_name
  outbound_function_arn                = module.compute.outbound_function_arn
  outbound_origination_phone_number_id = var.outbound_origination_phone_number_id
  log_retention_days                   = var.log_retention_days
}

module "agent" {
  source                          = "../../modules/agent"
  conversation_history_table_name = module.data.conversation_history_table_name
  conversation_history_table_arn  = module.data.conversation_history_table_arn
  follow_up_function_name         = module.follow_up.follow_up_function_name
  follow_up_function_arn          = module.follow_up.follow_up_function_arn

  environment = var.environment

  enable_agentcore_gateway = var.enable_agentcore_gateway
  enable_agentcore_memory  = var.enable_agentcore_memory

  kms_key_arn              = module.data.kms_key_arn
  reports_table_name       = module.data.reports_table_name
  reports_table_arn        = module.data.reports_table_arn
  incidents_table_name     = module.data.incidents_table_name
  incidents_table_arn      = module.data.incidents_table_arn
  places_table_name        = module.data.places_table_name
  places_table_arn         = module.data.places_table_arn
  users_table_name         = module.data.users_table_name
  users_table_arn          = module.data.users_table_arn
  pending_media_table_name = module.data.pending_media_table_name
  pending_media_table_arn  = module.data.pending_media_table_arn
  audit_log_table_name     = module.data.audit_log_table_name
  audit_log_table_arn      = module.data.audit_log_table_arn
  ingest_queue_arn         = module.data.ingest_queue_arn
  ingest_queue_url         = module.data.ingest_queue_url

  ingest_queue_visibility_timeout_seconds = module.data.ingest_queue_visibility_timeout_seconds
  events_bus_name                         = module.data.events_bus_name
  events_bus_arn                          = module.data.events_bus_arn

  routing_rules_json        = var.routing_rules_json
  escalate_report_threshold = var.escalate_report_threshold
  escalate_days_threshold   = var.escalate_days_threshold
  max_places_per_user       = var.max_places_per_user
  default_place_radius_m    = var.default_place_radius_m
  recent_window_hours       = var.recent_window_hours
  log_retention_days        = var.log_retention_days
  log_level                 = var.log_level
  bedrock_model_id          = var.bedrock_model_id

  outbound_function_name = module.compute.outbound_function_name
  outbound_function_arn  = module.compute.outbound_function_arn
}

module "portal" {
  follow_up_function_arn       = module.follow_up.follow_up_function_arn
  follow_up_scheduler_role_arn = module.follow_up.follow_up_scheduler_role_arn
  follow_up_delay_minutes      = var.follow_up_delay_minutes
  source                       = "../../modules/portal"

  environment = var.environment

  kms_key_arn          = module.data.kms_key_arn
  incidents_table_name = module.data.incidents_table_name
  incidents_table_arn  = module.data.incidents_table_arn
  incidents_stream_arn = module.data.incidents_stream_arn
  reports_table_name   = module.data.reports_table_name
  reports_table_arn    = module.data.reports_table_arn
  audit_log_table_name = module.data.audit_log_table_name
  audit_log_table_arn  = module.data.audit_log_table_arn
  users_table_name     = module.data.users_table_name
  users_table_arn      = module.data.users_table_arn
  events_bus_name      = module.data.events_bus_name
  events_bus_arn       = module.data.events_bus_arn

  routing_rules_json            = var.routing_rules_json
  staff_users                   = var.staff_users
  user_pool_deletion_protection = var.environment == "prod" ? "ACTIVE" : "INACTIVE"
  log_retention_days            = var.log_retention_days
  log_level                     = var.log_level
}
