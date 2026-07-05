#!/usr/bin/env python3
"""Deploy or destroy the dev Baskt account search-index Lambda.

Usage:
    python baskt_account_search_lambda.py --create
    python baskt_account_search_lambda.py --destroy
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Dict

import boto3
from botocore.exceptions import ClientError

sys.path.append(str(Path(__file__).resolve().parents[3]))
from aws_env import load_aws_env

OPENSEARCH_INFRASTRUCTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "opensearch"
    / "model_portfolio_opensearch"
)
sys.path.append(str(OPENSEARCH_INFRASTRUCTURE_PATH))
from model_portfolio_opensearch import (
    BASKT_ACCOUNT_INDEX_NAME,
    DOMAIN_NAME,
    REGION,
)


load_aws_env()

TABLE_NAME = "dev_baskt_account_dynamodb"
FUNCTION_NAME = "dev-baskt-account-search-indexer"
ROLE_NAME = "dev-baskt-account-search-indexer-role"
OPENSEARCH_POLICY_NAME = "dev-baskt-account-search-indexer-opensearch"
HANDLER_PATH = Path(__file__).with_name("handler.py")

LAMBDA_BASIC_POLICY_ARN = (
    "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
)
LAMBDA_DYNAMODB_POLICY_ARN = (
    "arn:aws:iam::aws:policy/service-role/AWSLambdaDynamoDBExecutionRole"
)


def _deployment_zip() -> bytes:
    """Package the Lambda handler into an in-memory zip archive."""
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(HANDLER_PATH, arcname="handler.py")
    return archive_buffer.getvalue()


def _ensure_role(iam: Any, domain_arn: str) -> str:
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
            Description="Indexes public Baskt account changes in OpenSearch.",
        )["Role"]

    for policy_arn in (LAMBDA_BASIC_POLICY_ARN, LAMBDA_DYNAMODB_POLICY_ARN):
        iam.attach_role_policy(RoleName=ROLE_NAME, PolicyArn=policy_arn)

    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName=OPENSEARCH_POLICY_NAME,
        PolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["es:ESHttpPost"],
                        # Bulk requests target the domain-level /_bulk path;
                        # the handler restricts each operation to the account index.
                        "Resource": f"{domain_arn}/*",
                    }
                ],
            }
        ),
    )
    return role["Arn"]


def _domain_configuration(opensearch: Any) -> Dict[str, str]:
    """Return the managed OpenSearch domain ARN and HTTPS endpoint."""
    domain = opensearch.describe_domain(DomainName=DOMAIN_NAME)["DomainStatus"]
    endpoint = domain.get("Endpoint")
    if endpoint is None:
        endpoints = domain.get("Endpoints", {})
        endpoint = endpoints.get("vpc") or endpoints.get("dualstack")
    if endpoint is None:
        raise RuntimeError(f"OpenSearch domain '{DOMAIN_NAME}' has no endpoint")
    return {"arn": domain["ARN"], "endpoint": f"https://{endpoint}"}


def _latest_stream_arn(dynamodb: Any) -> str:
    """Return the enabled stream ARN for the Baskt account table."""
    table = dynamodb.describe_table(TableName=TABLE_NAME)["Table"]
    stream_arn = table.get("LatestStreamArn")
    if not stream_arn:
        raise RuntimeError(f"DynamoDB Streams is not enabled on '{TABLE_NAME}'")
    return stream_arn


def _upsert_function(
    lambda_client: Any,
    role_arn: str,
    opensearch_endpoint: str,
    stream_arn: str,
) -> None:
    """Create the Lambda function or update its code and configuration."""
    environment = {
        "Variables": {
            "OPENSEARCH_ENDPOINT": opensearch_endpoint,
            "OPENSEARCH_INDEX": BASKT_ACCOUNT_INDEX_NAME,
            "OPENSEARCH_SERVICE": "es",
            "EXPECTED_STREAM_ARN": stream_arn,
        }
    }
    deployment_zip = _deployment_zip()
    try:
        lambda_client.get_function(FunctionName=FUNCTION_NAME)
    except lambda_client.exceptions.ResourceNotFoundException:
        for attempt in range(6):
            try:
                lambda_client.create_function(
                    FunctionName=FUNCTION_NAME,
                    Runtime="python3.12",
                    Role=role_arn,
                    Handler="handler.lambda_handler",
                    Code={"ZipFile": deployment_zip},
                    Description="Indexes public Baskt account changes in OpenSearch.",
                    Timeout=30,
                    MemorySize=256,
                    Environment=environment,
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
            ZipFile=deployment_zip,
            Publish=False,
        )
        lambda_client.get_waiter("function_updated_v2").wait(
            FunctionName=FUNCTION_NAME
        )
        lambda_client.update_function_configuration(
            FunctionName=FUNCTION_NAME,
            Role=role_arn,
            Runtime="python3.12",
            Handler="handler.lambda_handler",
            Timeout=30,
            MemorySize=256,
            Environment=environment,
        )

    lambda_client.get_waiter("function_active_v2").wait(FunctionName=FUNCTION_NAME)


def _ensure_event_source(lambda_client: Any, stream_arn: str) -> str:
    """Create or enable the DynamoDB stream event-source mapping."""
    mappings = lambda_client.list_event_source_mappings(
        FunctionName=FUNCTION_NAME,
        EventSourceArn=stream_arn,
    )["EventSourceMappings"]
    if mappings:
        mapping = mappings[0]
        if mapping.get("State") == "Disabled":
            lambda_client.update_event_source_mapping(
                UUID=mapping["UUID"],
                Enabled=True,
                BatchSize=100,
                FunctionResponseTypes=["ReportBatchItemFailures"],
            )
        return mapping["UUID"]

    mapping = lambda_client.create_event_source_mapping(
        EventSourceArn=stream_arn,
        FunctionName=FUNCTION_NAME,
        StartingPosition="LATEST",
        BatchSize=100,
        Enabled=True,
        BisectBatchOnFunctionError=True,
        FunctionResponseTypes=["ReportBatchItemFailures"],
    )
    return mapping["UUID"]


def create_lambda() -> None:
    """Deploy the stream consumer Lambda and connect it to DynamoDB."""
    iam = boto3.client("iam")
    dynamodb = boto3.client("dynamodb", region_name=REGION)
    lambda_client = boto3.client("lambda", region_name=REGION)
    opensearch = boto3.client("opensearch", region_name=REGION)

    domain = _domain_configuration(opensearch)
    stream_arn = _latest_stream_arn(dynamodb)
    role_arn = _ensure_role(iam, domain["arn"])
    _upsert_function(lambda_client, role_arn, domain["endpoint"], stream_arn)
    mapping_id = _ensure_event_source(lambda_client, stream_arn)

    print(f"Lambda function: {FUNCTION_NAME}")
    print(f"DynamoDB stream: {stream_arn}")
    print(f"Event-source mapping: {mapping_id}")
    print(f"OpenSearch endpoint: {domain['endpoint']}")
    print(f"OpenSearch index: {BASKT_ACCOUNT_INDEX_NAME}")


def destroy_lambda() -> None:
    """Delete the Lambda, its event mapping, and its execution role."""
    iam = boto3.client("iam")
    lambda_client = boto3.client("lambda", region_name=REGION)

    mappings = lambda_client.list_event_source_mappings(
        FunctionName=FUNCTION_NAME
    )["EventSourceMappings"]
    for mapping in mappings:
        lambda_client.delete_event_source_mapping(UUID=mapping["UUID"])

    try:
        lambda_client.delete_function(FunctionName=FUNCTION_NAME)
    except lambda_client.exceptions.ResourceNotFoundException:
        pass

    try:
        iam.delete_role_policy(
            RoleName=ROLE_NAME,
            PolicyName=OPENSEARCH_POLICY_NAME,
        )
        for policy_arn in (LAMBDA_BASIC_POLICY_ARN, LAMBDA_DYNAMODB_POLICY_ARN):
            iam.detach_role_policy(RoleName=ROLE_NAME, PolicyArn=policy_arn)
        iam.delete_role(RoleName=ROLE_NAME)
    except iam.exceptions.NoSuchEntityException:
        pass

    print(f"Deleted Lambda infrastructure for {FUNCTION_NAME}")


def main() -> None:
    """Parse deployment arguments and run the selected operation."""
    parser = argparse.ArgumentParser(
        description="Manage the dev Baskt account search-index Lambda."
    )
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--create", action="store_true")
    operation.add_argument("--destroy", action="store_true")
    args = parser.parse_args()

    try:
        if args.create:
            create_lambda()
        else:
            destroy_lambda()
    except (ClientError, RuntimeError) as error:
        print(f"Failed to manage {FUNCTION_NAME}: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
