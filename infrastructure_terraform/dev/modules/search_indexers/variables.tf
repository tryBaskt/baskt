variable "environment" { type = string }
variable "aws_region" { type = string }
variable "aws_account_id" { type = string }
variable "aws_partition" { type = string }
variable "opensearch_arn" { type = string }
variable "opensearch_endpoint" { type = string }
variable "model_portfolio_table_arn" { type = string }
variable "model_portfolio_stream_arn" { type = string }
variable "baskt_account_table_arn" { type = string }
variable "baskt_account_stream_arn" { type = string }
variable "log_retention_days" { type = number }
variable "tags" {
  type    = map(string)
  default = {}
}
