variable "user_pool_name" {
  description = "Name of the dev Cognito user pool."
  type        = string
}

variable "app_client_name" {
  description = "Name of the dev Cognito user pool app client."
  type        = string
}

variable "user_pool_domain" {
  description = "Cognito hosted UI domain prefix for the dev user pool."
  type        = string
}

variable "callback_urls" {
  description = "Allowed OAuth callback URLs for the dev Cognito app client."
  type        = list(string)
}

variable "logout_urls" {
  description = "Allowed logout URLs for the dev Cognito app client."
  type        = list(string)
}

variable "common_tags" {
  description = "Tags applied to managed dev infrastructure resources."
  type        = map(string)
}
