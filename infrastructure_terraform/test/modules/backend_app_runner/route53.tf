data "aws_route53_zone" "public" {
  name         = var.hosted_zone_name
  private_zone = false
}

resource "aws_route53_record" "backend_domain" {
  count   = local.create_backend_service ? 1 : 0
  zone_id = data.aws_route53_zone.public.zone_id
  name    = var.api_domain_name
  type    = "CNAME"
  ttl     = 300
  records = [aws_apprunner_custom_domain_association.backend[0].dns_target]
}

resource "aws_route53_record" "backend_domain_validation" {
  count           = local.create_backend_service ? 1 : 0
  allow_overwrite = true
  zone_id         = data.aws_route53_zone.public.zone_id
  name            = tolist(aws_apprunner_custom_domain_association.backend[0].certificate_validation_records)[0].name
  type            = tolist(aws_apprunner_custom_domain_association.backend[0].certificate_validation_records)[0].type
  ttl             = 300
  records         = [tolist(aws_apprunner_custom_domain_association.backend[0].certificate_validation_records)[0].value]
}
