resource "aws_opensearch_domain" "model_portfolio_search" {
  domain_name    = "${var.environment}-model-portfolio-search"
  engine_version = "OpenSearch_3.5"

  cluster_config {
    instance_type            = "t3.small.search"
    instance_count           = 1
    dedicated_master_enabled = false
    zone_awareness_enabled   = false
  }

  ebs_options {
    ebs_enabled = true
    volume_type = "gp3"
    volume_size = 10
  }

  encrypt_at_rest {
    enabled = true
  }

  node_to_node_encryption {
    enabled = true
  }

  domain_endpoint_options {
    enforce_https       = true
    tls_security_policy = "Policy-Min-TLS-1-2-2019-07"
  }

  access_policies = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        AWS = "arn:${var.aws_partition}:iam::${var.aws_account_id}:root"
      }
      Action   = "es:ESHttp*"
      Resource = "arn:${var.aws_partition}:es:${var.aws_region}:${var.aws_account_id}:domain/${var.environment}-model-portfolio-search/*"
    }]
  })

  lifecycle {
    prevent_destroy = true
  }
}
