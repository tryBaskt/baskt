#!/usr/bin/env python3
"""Refresh OpenSearch search indices from existing DynamoDB records."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from typing import Any, Iterable


SEARCH_REFRESH_TARGETS = (
    {
        "name": "model portfolios",
        "table_suffix": "model-portfolio-dynamodb",
        "lambda_suffix": "model-portfolio-search-indexer",
    },
    {
        "name": "Baskt accounts",
        "table_suffix": "baskt-account-dynamodb",
        "lambda_suffix": "baskt-account-search-indexer",
    },
)


def _chunks(items: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def _scan_table(dynamodb: Any, table_name: str) -> list[dict[str, Any]]:
    paginator = dynamodb.get_paginator("scan")
    items: list[dict[str, Any]] = []
    for page in paginator.paginate(TableName=table_name):
        items.extend(page.get("Items", []))
    return items


def _table_stream_arn(dynamodb: Any, table_name: str) -> str:
    table = dynamodb.describe_table(TableName=table_name)["Table"]
    stream_arn = table.get("LatestStreamArn")
    if not stream_arn:
        raise RuntimeError(f"Table {table_name} does not have DynamoDB Streams enabled")
    return stream_arn


def _table_key_names(dynamodb: Any, table_name: str) -> list[str]:
    table = dynamodb.describe_table(TableName=table_name)["Table"]
    return [key["AttributeName"] for key in table["KeySchema"]]


def _stream_record(
    *,
    table_name: str,
    stream_arn: str,
    key_names: list[str],
    item: dict[str, Any],
    sequence_number: int,
) -> dict[str, Any]:
    keys = {name: item[name] for name in key_names}
    return {
        "eventID": f"refresh-{table_name}-{sequence_number}",
        "eventName": "MODIFY",
        "eventSource": "aws:dynamodb",
        "eventSourceARN": stream_arn,
        "eventVersion": "1.1",
        "awsRegion": stream_arn.split(":")[3],
        "dynamodb": {
            "ApproximateCreationDateTime": int(time.time()),
            "Keys": keys,
            "NewImage": item,
            "SequenceNumber": f"refresh-{sequence_number}",
            "SizeBytes": len(json.dumps(item, separators=(",", ":"))),
            "StreamViewType": "NEW_AND_OLD_IMAGES",
        },
    }


def _invoke_indexer(
    *,
    lambda_client: Any,
    function_name: str,
    records: list[dict[str, Any]],
) -> None:
    response = lambda_client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps({"Records": records}).encode("utf-8"),
    )
    payload = json.loads(response["Payload"].read().decode("utf-8") or "{}")
    if response.get("FunctionError"):
        raise RuntimeError(f"{function_name} failed: {payload}")
    failures = payload.get("batchItemFailures", [])
    if failures:
        raise RuntimeError(f"{function_name} reported batch failures: {failures}")


def _session(profile: str | None, region: str) -> Any:
    import boto3

    if not profile:
        return boto3.Session(region_name=region)

    credentials_output = subprocess.check_output(
        [
            "aws",
            "configure",
            "export-credentials",
            "--profile",
            profile,
            "--format",
            "env-no-export",
        ],
        text=True,
    )
    credentials = dict(
        line.split("=", 1)
        for line in credentials_output.splitlines()
        if "=" in line
    )
    return boto3.Session(
        aws_access_key_id=credentials["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=credentials["AWS_SECRET_ACCESS_KEY"],
        aws_session_token=credentials.get("AWS_SESSION_TOKEN"),
        region_name=region,
    )


def refresh_target(
    *,
    dynamodb: Any,
    lambda_client: Any,
    environment: str,
    target: dict[str, str],
    batch_size: int,
) -> int:
    table_name = f"{environment}-{target['table_suffix']}"
    function_name = f"{environment}-{target['lambda_suffix']}"
    stream_arn = _table_stream_arn(dynamodb, table_name)
    key_names = _table_key_names(dynamodb, table_name)
    items = _scan_table(dynamodb, table_name)

    refreshed_count = 0
    for batch_number, batch in enumerate(_chunks(items, batch_size), start=1):
        records = [
            _stream_record(
                table_name=table_name,
                stream_arn=stream_arn,
                key_names=key_names,
                item=item,
                sequence_number=refreshed_count + offset,
            )
            for offset, item in enumerate(batch, start=1)
        ]
        _invoke_indexer(
            lambda_client=lambda_client,
            function_name=function_name,
            records=records,
        )
        refreshed_count += len(records)
        print(
            f"Refreshed {len(records)} {target['name']} records "
            f"in batch {batch_number}"
        )

    print(f"Refreshed {refreshed_count} {target['name']} records from {table_name}")
    return refreshed_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh OpenSearch search indices from DynamoDB tables."
    )
    parser.add_argument("--environment", required=True, choices=("dev", "test", "stage", "prod"))
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument(
        "--profile",
        help="Optional AWS profile for local runs. Omit in GitHub Actions.",
    )
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()

    if args.batch_size < 1:
        raise ValueError("--batch-size must be positive")

    session = _session(args.profile, args.region)
    dynamodb = session.client("dynamodb", region_name=args.region)
    lambda_client = session.client("lambda", region_name=args.region)

    total = 0
    for target in SEARCH_REFRESH_TARGETS:
        total += refresh_target(
            dynamodb=dynamodb,
            lambda_client=lambda_client,
            environment=args.environment,
            target=target,
            batch_size=args.batch_size,
        )

    print(f"Search refresh complete. Refreshed {total} total records.")


if __name__ == "__main__":
    main()
