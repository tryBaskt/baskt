variable "user_pool_name" {
  description = "Name of the environment Cognito user pool."
  type        = string
}

variable "app_client_name" {
  description = "Name of the environment Cognito user pool app client."
  type        = string
}

variable "user_pool_domain" {
  description = "Cognito hosted UI domain prefix for the environment user pool."
  type        = string
}

variable "callback_urls" {
  description = "Allowed OAuth callback URLs for the environment Cognito app client."
  type        = list(string)
}

variable "logout_urls" {
  description = "Allowed logout URLs for the environment Cognito app client."
  type        = list(string)
}

variable "common_tags" {
  description = "Tags applied to managed environment infrastructure resources."
  type        = map(string)
}
