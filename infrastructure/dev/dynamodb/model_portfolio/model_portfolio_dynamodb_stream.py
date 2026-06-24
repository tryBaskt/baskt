#!/usr/bin/env python3
"""Enable or disable the stream on the dev model portfolio table.

Usage:
    python model_portfolio_dynamodb_stream.py --create
    python model_portfolio_dynamodb_stream.py --destroy
"""

import argparse
import sys
from pathlib import Path
from typing import Any, Dict

import boto3
from botocore.exceptions import ClientError

sys.path.append(str(Path(__file__).resolve().parents[1]))
from aws_env import load_aws_env


load_aws_env()

TABLE_NAME = "dev_model_portfolio_dynamodb"
REGION = "us-east-1"
STREAM_VIEW_TYPE = "NEW_AND_OLD_IMAGES"


def _describe_table(dynamodb: Any) -> Dict[str, Any]:
    """Return the model portfolio table description."""
    return dynamodb.describe_table(TableName=TABLE_NAME)["Table"]


def _wait_until_active(dynamodb: Any) -> Dict[str, Any]:
    """Wait until a DynamoDB table update has completed."""
    dynamodb.get_waiter("table_exists").wait(
        TableName=TABLE_NAME,
        WaiterConfig={"Delay": 5, "MaxAttempts": 25},
    )
    return _describe_table(dynamodb)


def enable_model_portfolio_stream() -> str:
    """Enable a NEW_AND_OLD_IMAGES stream and return its ARN."""
    dynamodb = boto3.client("dynamodb", region_name=REGION)
    table = _describe_table(dynamodb)
    stream = table.get("StreamSpecification", {})

    if stream.get("StreamEnabled") and stream.get("StreamViewType") == STREAM_VIEW_TYPE:
        stream_arn = table["LatestStreamArn"]
        print(f"Stream is already enabled: {stream_arn}")
        return stream_arn

    if stream.get("StreamEnabled"):
        dynamodb.update_table(
            TableName=TABLE_NAME,
            StreamSpecification={"StreamEnabled": False},
        )
        _wait_until_active(dynamodb)

    dynamodb.update_table(
        TableName=TABLE_NAME,
        StreamSpecification={
            "StreamEnabled": True,
            "StreamViewType": STREAM_VIEW_TYPE,
        },
    )
    table = _wait_until_active(dynamodb)
    stream_arn = table["LatestStreamArn"]
    print(f"Enabled {STREAM_VIEW_TYPE} stream: {stream_arn}")
    return stream_arn


def disable_model_portfolio_stream() -> None:
    """Disable the model portfolio DynamoDB stream if it is enabled."""
    dynamodb = boto3.client("dynamodb", region_name=REGION)
    table = _describe_table(dynamodb)
    stream = table.get("StreamSpecification", {})

    if not stream.get("StreamEnabled"):
        print("Stream is already disabled.")
        return

    dynamodb.update_table(
        TableName=TABLE_NAME,
        StreamSpecification={"StreamEnabled": False},
    )
    _wait_until_active(dynamodb)
    print("Disabled model portfolio stream.")


def main() -> None:
    """Parse the requested stream operation and execute it."""
    parser = argparse.ArgumentParser(
        description=f"Manage the DynamoDB stream for {TABLE_NAME}."
    )
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--create", action="store_true", help="Enable the stream")
    operation.add_argument("--destroy", action="store_true", help="Disable the stream")
    args = parser.parse_args()

    try:
        if args.create:
            enable_model_portfolio_stream()
        else:
            disable_model_portfolio_stream()
    except ClientError as error:
        aws_error = error.response.get("Error", {})
        print(
            f"Failed to manage stream for {TABLE_NAME}: "
            f"{aws_error.get('Code', 'UnknownError')}: "
            f"{aws_error.get('Message', str(error))}"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
