#!/usr/bin/env python3
"""Create or destroy the development Baskt account DynamoDB table.

Usage:
    python baskt_account_dynamodb.py --create
    python baskt_account_dynamodb.py --destroy
"""

import argparse
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


sys.path.append(str(Path(__file__).resolve().parents[2]))
from aws_env import load_aws_env


load_aws_env()

CONFIGURATIONS = {
    "table_name": "dev_baskt_account_dynamodb",
    "region": "us-east-1",
    "partition_key": "cognito_user_id",
    "partition_key_attribute_type": "S",
    "partition_key_key_type": "HASH",
    "display_name_index": "display_name_index",
    "display_name_attribute": "display_name",
    "stream_view_type": "NEW_AND_OLD_IMAGES",
}


def wait_until_table_active(dynamodb):
    """Wait for the account table to finish its current update."""
    table_name = CONFIGURATIONS["table_name"]
    dynamodb.get_waiter("table_exists").wait(
        TableName=table_name,
        WaiterConfig={"Delay": 5, "MaxAttempts": 120},
    )
    return dynamodb.describe_table(TableName=table_name)["Table"]


def ensure_baskt_account_stream(dynamodb, table):
    """Enable the account stream with new and old item images."""
    table_name = CONFIGURATIONS["table_name"]
    stream_view_type = CONFIGURATIONS["stream_view_type"]
    stream = table.get("StreamSpecification", {})

    if stream.get("StreamEnabled") and stream.get("StreamViewType") == stream_view_type:
        print(f"Stream is already enabled: {table['LatestStreamArn']}")
        return table

    if stream.get("StreamEnabled"):
        print("Disabling existing stream configuration")
        dynamodb.update_table(
            TableName=table_name,
            StreamSpecification={"StreamEnabled": False},
        )
        wait_until_table_active(dynamodb)

    print(f"Enabling {stream_view_type} stream")
    dynamodb.update_table(
        TableName=table_name,
        StreamSpecification={
            "StreamEnabled": True,
            "StreamViewType": stream_view_type,
        },
    )
    table = wait_until_table_active(dynamodb)
    print(f"Stream enabled: {table['LatestStreamArn']}")
    return table


def ensure_display_name_index(dynamodb, table):
    """Create the display-name GSI when it is not already present."""
    index_name = CONFIGURATIONS["display_name_index"]
    existing_indexes = table.get("GlobalSecondaryIndexes", [])
    if any(index["IndexName"] == index_name for index in existing_indexes):
        print(f"Index {index_name} already exists")
        return table

    table_name = CONFIGURATIONS["table_name"]
    display_name_attribute = CONFIGURATIONS["display_name_attribute"]
    print(f"Creating global secondary index: {index_name}")
    dynamodb.update_table(
        TableName=table_name,
        AttributeDefinitions=[
            {
                "AttributeName": display_name_attribute,
                "AttributeType": "S",
            }
        ],
        GlobalSecondaryIndexUpdates=[
            {
                "Create": {
                    "IndexName": index_name,
                    "KeySchema": [
                        {
                            "AttributeName": display_name_attribute,
                            "KeyType": "HASH",
                        }
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            }
        ],
    )
    return dynamodb.describe_table(TableName=table_name)["Table"]


def create_dev_baskt_account_dynamodb():
    """Create the development Baskt account table if it does not exist."""
    table_name = CONFIGURATIONS["table_name"]
    region = CONFIGURATIONS["region"]
    dynamodb = boto3.client("dynamodb", region_name=region)

    table_config = {
        "TableName": table_name,
        "AttributeDefinitions": [
            {
                "AttributeName": CONFIGURATIONS["partition_key"],
                "AttributeType": CONFIGURATIONS["partition_key_attribute_type"],
            },
            {
                "AttributeName": CONFIGURATIONS["display_name_attribute"],
                "AttributeType": "S",
            },
        ],
        "KeySchema": [
            {
                "AttributeName": CONFIGURATIONS["partition_key"],
                "KeyType": CONFIGURATIONS["partition_key_key_type"],
            }
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": CONFIGURATIONS["display_name_index"],
                "KeySchema": [
                    {
                        "AttributeName": CONFIGURATIONS["display_name_attribute"],
                        "KeyType": "HASH",
                    }
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        "StreamSpecification": {
            "StreamEnabled": True,
            "StreamViewType": CONFIGURATIONS["stream_view_type"],
        },
        "BillingMode": "PAY_PER_REQUEST",
        "DeletionProtectionEnabled": False,
    }

    try:
        try:
            existing_table = dynamodb.describe_table(TableName=table_name)["Table"]
            print(f"Table {table_name} already exists")
            print(f"ARN: {existing_table['TableArn']}")
            print(f"Status: {existing_table['TableStatus']}")
            table = ensure_baskt_account_stream(dynamodb, existing_table)
            return ensure_display_name_index(dynamodb, table)
        except ClientError as error:
            if error.response["Error"]["Code"] != "ResourceNotFoundException":
                raise

        print(f"Creating DynamoDB table: {table_name}")
        response = dynamodb.create_table(**table_config)

        dynamodb.get_waiter("table_exists").wait(
            TableName=table_name,
            WaiterConfig={"Delay": 5, "MaxAttempts": 25},
        )

        table = dynamodb.describe_table(TableName=table_name)["Table"]
        print(f"Table {table_name} is active")
        print(f"ARN: {table['TableArn']}")
        return response
    except ClientError as error:
        print(f"Failed to create {table_name}: {error.response['Error']['Message']}")
        sys.exit(1)


def delete_dev_baskt_account_dynamodb():
    """Delete the development Baskt account table if it exists."""
    table_name = CONFIGURATIONS["table_name"]
    region = CONFIGURATIONS["region"]
    dynamodb = boto3.client("dynamodb", region_name=region)

    try:
        try:
            dynamodb.describe_table(TableName=table_name)
        except ClientError as error:
            if error.response["Error"]["Code"] == "ResourceNotFoundException":
                print(f"Table {table_name} does not exist")
                return None
            raise

        print(f"Deleting DynamoDB table: {table_name}")
        response = dynamodb.delete_table(TableName=table_name)

        dynamodb.get_waiter("table_not_exists").wait(
            TableName=table_name,
            WaiterConfig={"Delay": 5, "MaxAttempts": 25},
        )

        print(f"Table {table_name} has been deleted")
        return response
    except ClientError as error:
        print(f"Failed to delete {table_name}: {error.response['Error']['Message']}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description=f"Create or destroy the {CONFIGURATIONS['table_name']} table"
    )
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--create", action="store_true", help="Create the table")
    actions.add_argument("--destroy", action="store_true", help="Delete the table")
    args = parser.parse_args()

    if args.create:
        create_dev_baskt_account_dynamodb()
    else:
        delete_dev_baskt_account_dynamodb()


if __name__ == "__main__":
    main()
