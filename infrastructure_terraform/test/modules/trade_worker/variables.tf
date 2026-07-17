variable "environment" { type = string }
variable "aws_region" { type = string }
variable "aws_account_id" { type = string }
variable "aws_partition" { type = string }
variable "queue_arn" { type = string }
variable "queue_url" { type = string }
variable "trade_worker_image_uri" { type = string }
variable "cognito_region" { type = string }
variable "cognito_user_pool_id" { type = string }
variable "cognito_app_client_id" { type = string }
variable "trade_worker_environment" {
  type      = map(string)
  sensitive = true
}
