resource "aws_cognito_user_pool" "baskt" {
  name                = var.user_pool_name
  deletion_protection = "INACTIVE"

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  mfa_configuration        = "OFF"

  password_policy {
    minimum_length                   = 8
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    require_uppercase                = true
    temporary_password_validity_days = 7
  }

  username_configuration {
    case_sensitive = false
  }

  verification_message_template {
    default_email_option = "CONFIRM_WITH_CODE"
  }

  email_configuration {
    email_sending_account = "COGNITO_DEFAULT"
  }

  admin_create_user_config {
    allow_admin_create_user_only = false
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }

    recovery_mechanism {
      name     = "verified_phone_number"
      priority = 2
    }
  }

  schema {
    name                     = "alpaca_account_id"
    attribute_data_type      = "String"
    developer_only_attribute = false
    mutable                  = false
    required                 = false

    string_attribute_constraints {}
  }

  schema {
    name                     = "alpaca_account_num"
    attribute_data_type      = "String"
    developer_only_attribute = false
    mutable                  = false
    required                 = false

    string_attribute_constraints {}
  }

  schema {
    name                     = "alpaca_acct_id"
    attribute_data_type      = "String"
    developer_only_attribute = false
    mutable                  = true
    required                 = false

    string_attribute_constraints {}
  }

  schema {
    name                     = "alpaca_acct_num"
    attribute_data_type      = "String"
    developer_only_attribute = false
    mutable                  = true
    required                 = false

    string_attribute_constraints {}
  }

  schema {
    name                     = "username"
    attribute_data_type      = "String"
    developer_only_attribute = false
    mutable                  = true
    required                 = false

    string_attribute_constraints {}
  }

  tags = var.common_tags
}
