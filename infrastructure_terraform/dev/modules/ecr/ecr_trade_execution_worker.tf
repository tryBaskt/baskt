resource "aws_ecr_repository" "trade_execution_worker" {
  name                 = "${var.environment}-trade-execution-queue-worker"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  lifecycle {
    prevent_destroy = true
  }
}
