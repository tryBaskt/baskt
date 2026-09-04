resource "aws_ecr_repository" "trade_execution_worker" {
  name                 = "${var.environment}-trade-execution-queue-worker"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}
