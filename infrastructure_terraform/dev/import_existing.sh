#!/usr/bin/env bash

set -euo pipefail

export AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-$AWS_REGION}"

account_id="$(aws sts get-caller-identity --query Account --output text)"
if [[ "$account_id" != "499133675835" ]]; then
  echo "Refusing to import from unexpected AWS account: $account_id" >&2
  exit 1
fi

worker_image_uri="$(
  aws lambda get-function \
    --function-name dev-trade-execution-queue-worker \
    --query Code.ImageUri \
    --output text 2>/dev/null || true
)"
if [[ -n "$worker_image_uri" && "$worker_image_uri" != "None" ]]; then
  export TF_VAR_trade_worker_image_uri="$worker_image_uri"
fi

state_has() {
  terraform state show "$1" >/dev/null 2>&1
}

import_resource() {
  local address="$1"
  local id="$2"

  if state_has "$address"; then
    echo "Already imported: $address"
    return
  fi
  if [[ -z "$id" || "$id" == "None" ]]; then
    echo "Could not discover import ID for: $address" >&2
    exit 1
  fi

  echo "Importing $address"
  terraform import "$address" "$id"
}

queue_url() {
  aws sqs get-queue-url --queue-name "$1" --query QueueUrl --output text
}

mapping_uuid() {
  aws lambda list-event-source-mappings \
    --function-name "$1" \
    --event-source-arn "$2" \
    --query 'EventSourceMappings[0].UUID' \
    --output text
}

import_resource module.dynamodb.aws_dynamodb_table.baskt_account \
  dev-baskt-account-dynamodb
import_resource module.dynamodb.aws_dynamodb_table.model_portfolio \
  dev-model-portfolio-dynamodb
import_resource module.dynamodb.aws_dynamodb_table.model_portfolio_follower \
  dev-model-portfolio-follower-dynamodb
import_resource module.dynamodb.aws_dynamodb_table.model_portfolio_update_lock \
  dev-model-portfolio-update-lock-dynamodb
import_resource module.dynamodb.aws_dynamodb_table.order \
  dev-order-dynamodb
import_resource module.dynamodb.aws_dynamodb_table.user_trade_lock \
  dev-user-trade-lock-dynamodb

import_resource module.ecr.aws_ecr_repository.trade_execution_worker \
  dev-trade-execution-queue-worker

import_resource module.queues.aws_sqs_queue.trade_execution_dlq \
  "$(queue_url dev-trade-execution-dlq)"
import_resource module.queues.aws_sqs_queue.trade_execution \
  "$(queue_url dev-trade-execution-queue)"

import_resource module.trade_worker.aws_iam_role.trade_worker \
  dev-trade-execution-queue-worker-role
import_resource module.trade_worker.aws_iam_role_policy.trade_worker_sqs \
  dev-trade-execution-queue-worker-role:dev-trade-execution-queue-worker-sqs
import_resource module.trade_worker.aws_iam_role_policy.trade_worker_dynamodb \
  dev-trade-execution-queue-worker-role:dev-trade-execution-queue-worker-dynamodb
import_resource module.trade_worker.aws_iam_role_policy_attachment.trade_worker_basic_execution \
  dev-trade-execution-queue-worker-role/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
import_resource module.trade_worker.aws_iam_role.market_controller \
  dev-trade-execution-market-hours-controller-role
import_resource module.trade_worker.aws_iam_role.market_scheduler \
  dev-trade-execution-market-hours-scheduler-role

if [[ -z "$worker_image_uri" || "$worker_image_uri" == "None" ]]; then
  echo "Trade worker Lambda was not found; cannot import required worker resources." >&2
  exit 1
fi

import_resource module.trade_worker.aws_lambda_function.trade_execution_worker \
  dev-trade-execution-queue-worker
import_resource module.trade_worker.aws_iam_role_policy.market_controller \
  dev-trade-execution-market-hours-controller-role:dev-trade-execution-market-hours-controller
import_resource module.trade_worker.aws_iam_role_policy.market_scheduler \
  dev-trade-execution-market-hours-scheduler-role:dev-trade-execution-market-hours-scheduler
import_resource module.trade_worker.aws_lambda_function.market_hours_controller \
  dev-trade-execution-market-hours-controller
import_resource module.trade_worker.aws_lambda_event_source_mapping.trade_execution_queue \
  "$(mapping_uuid \
    dev-trade-execution-queue-worker \
    "$(aws sqs get-queue-attributes \
      --queue-url "$(queue_url dev-trade-execution-queue)" \
      --attribute-names QueueArn \
      --query Attributes.QueueArn \
      --output text)")"
import_resource module.trade_worker.aws_scheduler_schedule.market_prepare \
  default/dev-trade-execution-prepare
import_resource module.trade_worker.aws_scheduler_schedule.market_open \
  default/dev-trade-execution-open
import_resource module.trade_worker.aws_scheduler_schedule.market_early_close \
  default/dev-trade-execution-early-close
import_resource module.trade_worker.aws_scheduler_schedule.market_close \
  default/dev-trade-execution-close

echo
echo "Import complete. Resources in state:"
terraform state list
