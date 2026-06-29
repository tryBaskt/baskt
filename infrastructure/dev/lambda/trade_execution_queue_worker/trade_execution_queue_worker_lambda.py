#!/usr/bin/env python3
"""Deploy or destroy the dev trade-execution queue worker Lambda image.

Usage:
    python trade_execution_queue_worker_lambda.py --create
    python trade_execution_queue_worker_lambda.py --destroy
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict

import boto3
from botocore.exceptions import ClientError

sys.path.append(str(Path(__file__).resolve().parents[3]))
from aws_env import load_aws_env


load_aws_env()

REGION = "us-east-1"
FUNCTION_NAME = "dev-trade-execution-queue-worker"
ROLE_NAME = "dev-trade-execution-queue-worker-role"
QUEUE_NAME = "dev-trade-execution-queue"
DLQ_NAME = "dev-trade-execution-dlq"
ECR_REPOSITORY_NAME = "dev-trade-execution-queue-worker"
IMAGE_TAG = "latest"
SQS_POLICY_NAME = "dev-trade-execution-queue-worker-sqs"
DYNAMODB_POLICY_NAME = "dev-trade-execution-queue-worker-dynamodb"
LAMBDA_BASIC_POLICY_ARN = (
    "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
)
LAMBDA_IMAGE_ARCHITECTURES = ["x86_64"]
LAMBDA_MEMORY_SIZE_MB = 2048
HANDLER_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[4]
ENV_KEYS_FOR_LAMBDA = (
    "ENV",
    "ALPACA_ENV",
    "DEV_COGNITO_REGION",
    "DEV_COGNITO_USER_POOL_ID",
    "DEV_COGNITO_APP_CLIENT_ID",
    "SANDBOX_ALPACA_BROKER_API_KEY",
    "SANDBOX_ALPACA_BROKER_API_SECRET",
    "LIVE_ALPACA_BROKER_API_KEY",
    "LIVE_ALPACA_BROKER_API_SECRET",
    "MODEL_PORTFOLIO_DYNAMODB",
    "PORTFOLIO_ALLOCATION_DYNAMODB",
    "ORDER_DYNAMODB",
    "MODEL_PORTFOLIO_FOLLOWER_DYNAMODB",
    "USER_TRADE_LOCK_DYNAMODB",
    "MODEL_PORTFOLIO_UPDATE_LOCK_DYNAMODB",
    "DEV_TRADE_EXECUTION_QUEUE_URL"
)


def _parse_dotenv(path: Path) -> Dict[str, str]:
    """Parse simple KEY=value lines from a dotenv file."""
    values: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _workspace_env() -> Dict[str, str]:
    """Return root .env values merged with the current process environment."""
    values: Dict[str, str] = {}
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        values.update(_parse_dotenv(env_path))
    values.update({key: value for key, value in os.environ.items()})
    return values


def _lambda_environment_variables(queue_url: str) -> Dict[str, str]:
    """Build Lambda environment variables from root .env and deployment state."""
    env_values = _workspace_env()
    variables = {
        key: env_values[key]
        for key in ENV_KEYS_FOR_LAMBDA
        if key in env_values and env_values[key] != ""
    }
    variables.setdefault("ENV", "dev")
    variables.setdefault("ALPACA_ENV", "sandbox")
    variables["DEV_TRADE_EXECUTION_QUEUE_URL"] = queue_url
    return variables


def _account_id() -> str:
    """Return the AWS account ID for the configured credentials."""
    return boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]


def _ensure_queue(sqs: Any) -> Dict[str, str]:
    """Create the queue and dead-letter queue and return their URLs and ARNs."""
    dlq_url = sqs.create_queue(
        QueueName=DLQ_NAME,
        Attributes={
            "MessageRetentionPeriod": str(14 * 24 * 60 * 60),
        },
    )["QueueUrl"]
    dlq_arn = sqs.get_queue_attributes(
        QueueUrl=dlq_url,
        AttributeNames=["QueueArn"],
    )["Attributes"]["QueueArn"]

    queue_url = sqs.create_queue(
        QueueName=QUEUE_NAME,
        Attributes={
            "VisibilityTimeout": "180",
            "MessageRetentionPeriod": str(4 * 24 * 60 * 60),
            "RedrivePolicy": json.dumps(
                {
                    "deadLetterTargetArn": dlq_arn,
                    "maxReceiveCount": 3,
                }
            ),
        },
    )["QueueUrl"]
    queue_arn = sqs.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=["QueueArn"],
    )["Attributes"]["QueueArn"]

    return {
        "queue_url": queue_url,
        "queue_arn": queue_arn,
        "dlq_url": dlq_url,
        "dlq_arn": dlq_arn,
    }


def _ensure_ecr_repository(ecr: Any) -> str:
    """Create the ECR repository if needed and return its URI."""
    try:
        repository = ecr.describe_repositories(
            repositoryNames=[ECR_REPOSITORY_NAME],
        )["repositories"][0]
    except ecr.exceptions.RepositoryNotFoundException:
        repository = ecr.create_repository(
            repositoryName=ECR_REPOSITORY_NAME,
            imageScanningConfiguration={"scanOnPush": True},
            encryptionConfiguration={"encryptionType": "AES256"},
        )["repository"]
    return repository["repositoryUri"]


def _run(command: list[str]) -> None:
    """Run a deployment command and raise on failure."""
    subprocess.run(command, check=True)


def _build_and_push_image(ecr: Any, repository_uri: str) -> str:
    """Build the Lambda Docker image and push it to ECR."""
    auth = ecr.get_authorization_token()["authorizationData"][0]
    registry = auth["proxyEndpoint"].replace("https://", "")
    password = subprocess.check_output(
        ["aws", "ecr", "get-login-password", "--region", REGION],
        text=True,
    ).strip()
    subprocess.run(
        ["docker", "login", "--username", "AWS", "--password-stdin", registry],
        input=password,
        text=True,
        check=True,
    )

    local_image = f"{ECR_REPOSITORY_NAME}:{IMAGE_TAG}"
    image_uri = f"{repository_uri}:{IMAGE_TAG}"
    _run(
        [
            "docker",
            "buildx",
            "build",
            "--platform",
            "linux/amd64",
            "--load",
            "-f",
            str(HANDLER_DIR / "Dockerfile"),
            "-t",
            local_image,
            str(REPO_ROOT),
        ]
    )
    _run(["docker", "tag", local_image, image_uri])
    _run(["docker", "push", image_uri])
    return image_uri


def _ensure_role(iam: Any, queue_arn: str) -> str:
    """Create or update the Lambda execution role and return its ARN."""
    assume_role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    try:
        role = iam.get_role(RoleName=ROLE_NAME)["Role"]
    except iam.exceptions.NoSuchEntityException:
        role = iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(assume_role_policy),
            Description="Consumes queued trade-execution requests.",
        )["Role"]

    iam.attach_role_policy(RoleName=ROLE_NAME, PolicyArn=LAMBDA_BASIC_POLICY_ARN)
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName=SQS_POLICY_NAME,
        PolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "sqs:ReceiveMessage",
                            "sqs:DeleteMessage",
                            "sqs:GetQueueAttributes",
                            "sqs:ChangeMessageVisibility",
                        ],
                        "Resource": queue_arn,
                    }
                ],
            }
        ),
    )
    account_id = _account_id()
    dynamodb_table_resources = [
        f"arn:aws:dynamodb:{REGION}:{account_id}:table/dev_*",
        f"arn:aws:dynamodb:{REGION}:{account_id}:table/dev_*/index/*",
    ]
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName=DYNAMODB_POLICY_NAME,
        PolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "dynamodb:GetItem",
                            "dynamodb:PutItem",
                            "dynamodb:BatchWriteItem",
                            "dynamodb:UpdateItem",
                            "dynamodb:DeleteItem",
                            "dynamodb:Query",
                            "dynamodb:Scan",
                        ],
                        "Resource": dynamodb_table_resources,
                    }
                ],
            }
        ),
    )
    return role["Arn"]


def _upsert_function(
    lambda_client: Any,
    *,
    role_arn: str,
    image_uri: str,
    queue_url: str,
) -> None:
    """Create the Lambda image function or update its image/configuration."""
    environment = {"Variables": _lambda_environment_variables(queue_url)}
    try:
        lambda_client.get_function(FunctionName=FUNCTION_NAME)
    except lambda_client.exceptions.ResourceNotFoundException:
        for attempt in range(6):
            try:
                lambda_client.create_function(
                    FunctionName=FUNCTION_NAME,
                    PackageType="Image",
                    Role=role_arn,
                    Code={"ImageUri": image_uri},
                    Description="Forwards queued trade-execution jobs to the backend.",
                    Timeout=60,
                    MemorySize=LAMBDA_MEMORY_SIZE_MB,
                    Environment=environment,
                    Architectures=LAMBDA_IMAGE_ARCHITECTURES,
                )
                break
            except ClientError as error:
                if (
                    error.response.get("Error", {}).get("Code")
                    != "InvalidParameterValueException"
                    or attempt == 5
                ):
                    raise
                time.sleep(5)
    else:
        lambda_client.update_function_code(
            FunctionName=FUNCTION_NAME,
            ImageUri=image_uri,
            Publish=False,
        )
        lambda_client.get_waiter("function_updated_v2").wait(
            FunctionName=FUNCTION_NAME
        )
        lambda_client.update_function_configuration(
            FunctionName=FUNCTION_NAME,
            Role=role_arn,
            Timeout=60,
            MemorySize=LAMBDA_MEMORY_SIZE_MB,
            Environment=environment,
        )

    lambda_client.get_waiter("function_active_v2").wait(FunctionName=FUNCTION_NAME)


def _ensure_event_source(lambda_client: Any, queue_arn: str) -> str:
    """Create or enable the SQS event-source mapping."""
    mappings = lambda_client.list_event_source_mappings(
        FunctionName=FUNCTION_NAME,
        EventSourceArn=queue_arn,
    )["EventSourceMappings"]
    if mappings:
        mapping = mappings[0]
        if mapping.get("State") == "Disabled":
            lambda_client.update_event_source_mapping(
                UUID=mapping["UUID"],
                Enabled=True,
                BatchSize=10,
                FunctionResponseTypes=["ReportBatchItemFailures"],
            )
        return mapping["UUID"]

    mapping = lambda_client.create_event_source_mapping(
        EventSourceArn=queue_arn,
        FunctionName=FUNCTION_NAME,
        BatchSize=10,
        Enabled=True,
        FunctionResponseTypes=["ReportBatchItemFailures"],
    )
    return mapping["UUID"]


def create_worker() -> None:
    """Create or update the ECR image, SQS queue, and Lambda worker."""
    iam = boto3.client("iam")
    sqs = boto3.client("sqs", region_name=REGION)
    ecr = boto3.client("ecr", region_name=REGION)
    lambda_client = boto3.client("lambda", region_name=REGION)

    queue = _ensure_queue(sqs)
    repository_uri = _ensure_ecr_repository(ecr)
    image_uri = _build_and_push_image(ecr, repository_uri)
    role_arn = _ensure_role(iam, queue["queue_arn"])
    _upsert_function(
        lambda_client,
        role_arn=role_arn,
        image_uri=image_uri,
        queue_url=queue["queue_url"],
    )
    mapping_id = _ensure_event_source(lambda_client, queue["queue_arn"])

    print(f"Lambda function: {FUNCTION_NAME}")
    print(f"Lambda image: {image_uri}")
    print(f"SQS queue URL: {queue['queue_url']}")
    print(f"SQS queue ARN: {queue['queue_arn']}")
    print(f"Dead-letter queue URL: {queue['dlq_url']}")
    print(f"Event-source mapping: {mapping_id}")


def destroy_worker() -> None:
    """Delete the Lambda worker, event-source mapping, queues, role, and ECR repo."""
    iam = boto3.client("iam")
    sqs = boto3.client("sqs", region_name=REGION)
    ecr = boto3.client("ecr", region_name=REGION)
    lambda_client = boto3.client("lambda", region_name=REGION)

    try:
        function = lambda_client.get_function(FunctionName=FUNCTION_NAME)
        function_arn = function["Configuration"]["FunctionArn"]
    except lambda_client.exceptions.ResourceNotFoundException:
        function_arn = None

    if function_arn:
        mappings = lambda_client.list_event_source_mappings(
            FunctionName=FUNCTION_NAME,
        )["EventSourceMappings"]
        for mapping in mappings:
            lambda_client.delete_event_source_mapping(UUID=mapping["UUID"])
        lambda_client.delete_function(FunctionName=FUNCTION_NAME)
        print(f"Deleted Lambda function: {FUNCTION_NAME}")

    for queue_name in (QUEUE_NAME, DLQ_NAME):
        try:
            queue_url = sqs.get_queue_url(QueueName=queue_name)["QueueUrl"]
        except sqs.exceptions.QueueDoesNotExist:
            continue
        sqs.delete_queue(QueueUrl=queue_url)
        print(f"Deleted SQS queue: {queue_name}")

    try:
        iam.delete_role_policy(RoleName=ROLE_NAME, PolicyName=SQS_POLICY_NAME)
    except iam.exceptions.NoSuchEntityException:
        pass
    try:
        iam.delete_role_policy(RoleName=ROLE_NAME, PolicyName=DYNAMODB_POLICY_NAME)
    except iam.exceptions.NoSuchEntityException:
        pass
    try:
        iam.detach_role_policy(
            RoleName=ROLE_NAME,
            PolicyArn=LAMBDA_BASIC_POLICY_ARN,
        )
    except iam.exceptions.NoSuchEntityException:
        pass
    try:
        iam.delete_role(RoleName=ROLE_NAME)
        print(f"Deleted IAM role: {ROLE_NAME}")
    except iam.exceptions.NoSuchEntityException:
        pass

    try:
        ecr.delete_repository(
            repositoryName=ECR_REPOSITORY_NAME,
            force=True,
        )
        print(f"Deleted ECR repository: {ECR_REPOSITORY_NAME}")
    except ecr.exceptions.RepositoryNotFoundException:
        pass


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--create", action="store_true")
    action.add_argument("--destroy", action="store_true")
    return parser.parse_args()


def main() -> None:
    """Run the selected deployment action."""
    args = parse_args()
    if args.create:
        create_worker()
    else:
        destroy_worker()


if __name__ == "__main__":
    main()
