variable "environment" {
  type = string
}
variable "incidents_table_name" {
  type = string
}
variable "incidents_table_arn" {
  type = string
}
variable "reports_table_name" {
  type = string
}
variable "reports_table_arn" {
  type = string
}
variable "users_table_name" {
  type = string
}
variable "users_table_arn" {
  type = string
}
variable "kms_key_arn" {
  type = string
}
variable "outbound_function_name" {
  type = string
}
variable "outbound_function_arn" {
  type = string
}
variable "outbound_origination_phone_number_id" {
  type = string
}
variable "log_retention_days" {
  type    = number
  default = 14
}
