resource "aws_apigatewayv2_api" "backend" {
  name                         = "${var.environment}-backend"
  protocol_type                = "HTTP"
  disable_execute_api_endpoint = true
}

resource "aws_cloudwatch_log_group" "api_access" {
  name              = "/aws/apigateway/${var.environment}-backend"
  retention_in_days = 14
}

resource "aws_apigatewayv2_stage" "backend" {
  api_id      = aws_apigatewayv2_api.backend.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access.arn
    format = jsonencode({
      requestId        = "$context.requestId"
      routeKey         = "$context.routeKey"
      status           = "$context.status"
      responseLength   = "$context.responseLength"
      integrationError = "$context.integrationErrorMessage"
    })
  }
}

resource "aws_apigatewayv2_integration" "backend" {
  count                  = local.create_backend_function ? 1 : 0
  api_id                 = aws_apigatewayv2_api.backend.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.backend[0].invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 30000
}

resource "aws_apigatewayv2_route" "backend" {
  count     = local.create_backend_function ? 1 : 0
  api_id    = aws_apigatewayv2_api.backend.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.backend[0].id}"
  # FastAPI keeps the existing per-route Cognito authentication, including
  # unauthenticated account creation and CORS preflight requests.
}

resource "aws_lambda_permission" "api_gateway" {
  count          = local.create_backend_function ? 1 : 0
  statement_id   = "AllowBackendApiGateway"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.backend[0].function_name
  principal      = "apigateway.amazonaws.com"
  source_arn     = "${aws_apigatewayv2_api.backend.execution_arn}/*/*"
  source_account = var.aws_account_id
}

resource "aws_apigatewayv2_domain_name" "backend" {
  domain_name = var.api_domain_name
  domain_name_configuration {
    certificate_arn = aws_acm_certificate_validation.backend.certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }
}

resource "aws_apigatewayv2_api_mapping" "backend" {
  api_id      = aws_apigatewayv2_api.backend.id
  domain_name = aws_apigatewayv2_domain_name.backend.id
  stage       = aws_apigatewayv2_stage.backend.id
  depends_on  = [aws_apigatewayv2_route.backend, aws_lambda_permission.api_gateway]
}

resource "aws_route53_record" "backend_domain" {
  zone_id = data.aws_route53_zone.public.zone_id
  name    = var.api_domain_name
  type    = "A"

  alias {
    name                   = aws_apigatewayv2_domain_name.backend.domain_name_configuration[0].target_domain_name
    zone_id                = aws_apigatewayv2_domain_name.backend.domain_name_configuration[0].hosted_zone_id
    evaluate_target_health = false
  }
  depends_on = [aws_apigatewayv2_api_mapping.backend]
}
