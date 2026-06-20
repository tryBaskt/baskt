"""Synchronize model portfolio DynamoDB stream records to OpenSearch."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import boto3
from boto3.dynamodb.types import TypeDeserializer
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest


OPENSEARCH_ENDPOINT = os.environ["OPENSEARCH_ENDPOINT"].rstrip("/")
OPENSEARCH_INDEX = os.environ["OPENSEARCH_INDEX"]
EXPECTED_STREAM_ARN = os.environ.get("EXPECTED_STREAM_ARN")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
OPENSEARCH_SERVICE = os.environ.get("OPENSEARCH_SERVICE", "es")

_deserializer = TypeDeserializer()


def _deserialize_image(image: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a DynamoDB attribute map into ordinary Python values."""
    return {name: _deserializer.deserialize(value) for name, value in image.items()}


def _search_document(item: Dict[str, Any]) -> Dict[str, Any]:
    """Select the model portfolio fields that belong in the search index."""
    searchable_fields = (
        "portfolio_id",
        "portfolio_name",
        "description",
        "portfolio_owner_cognito_user_id",
        "created_at",
        "updated_at",
        "visibility",
    )
    return {
        field: item[field]
        for field in searchable_fields
        if field in item and item[field] is not None
    }


def _signed_post(path: str, body: bytes) -> Dict[str, Any]:
    """Send an IAM-signed POST request to OpenSearch."""
    url = f"{OPENSEARCH_ENDPOINT}/{path.lstrip('/')}"
    credentials = boto3.Session().get_credentials()
    if credentials is None:
        raise RuntimeError("Lambda could not obtain AWS credentials")

    aws_request = AWSRequest(
        method="POST",
        url=url,
        data=body,
        headers={"Content-Type": "application/x-ndjson"},
    )
    SigV4Auth(
        credentials.get_frozen_credentials(),
        OPENSEARCH_SERVICE,
        AWS_REGION,
    ).add_auth(aws_request)

    request = Request(
        url=url,
        data=body,
        headers=dict(aws_request.headers),
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"OpenSearch request failed with HTTP {error.code}: {response_body}"
        ) from error


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, List[Dict[str, str]]]:
    """Apply DynamoDB stream inserts, updates, and deletes to OpenSearch."""
    operations: List[Dict[str, str]] = []
    bulk_lines: List[str] = []

    for record in event.get("Records", []):
        if EXPECTED_STREAM_ARN and record.get("eventSourceARN") != EXPECTED_STREAM_ARN:
            continue

        event_name = record.get("eventName")
        dynamodb_record = record.get("dynamodb", {})
        sequence_number = str(dynamodb_record.get("SequenceNumber", ""))

        if event_name in {"INSERT", "MODIFY"}:
            item = _deserialize_image(dynamodb_record["NewImage"])
            portfolio_id = str(item["portfolio_id"])
            operations.append(
                {"operation": "index", "sequence_number": sequence_number}
            )
            bulk_lines.append(
                json.dumps(
                    {"index": {"_index": OPENSEARCH_INDEX, "_id": portfolio_id}},
                    separators=(",", ":"),
                )
            )
            bulk_lines.append(
                json.dumps(_search_document(item), separators=(",", ":"))
            )
        elif event_name == "REMOVE":
            keys = _deserialize_image(dynamodb_record["Keys"])
            portfolio_id = str(keys["portfolio_id"])
            operations.append(
                {"operation": "delete", "sequence_number": sequence_number}
            )
            bulk_lines.append(
                json.dumps(
                    {"delete": {"_index": OPENSEARCH_INDEX, "_id": portfolio_id}},
                    separators=(",", ":"),
                )
            )

    if not operations:
        return {"batchItemFailures": []}

    body = ("\n".join(bulk_lines) + "\n").encode("utf-8")
    try:
        response = _signed_post("_bulk", body)
    except Exception:
        return {
            "batchItemFailures": [
                {"itemIdentifier": operation["sequence_number"]}
                for operation in operations
            ]
        }

    failures: List[Dict[str, str]] = []
    response_items = response.get("items", [])
    if len(response_items) != len(operations):
        return {
            "batchItemFailures": [
                {"itemIdentifier": operation["sequence_number"]}
                for operation in operations
            ]
        }

    for operation, response_item in zip(operations, response_items):
        result = response_item.get(operation["operation"], {})
        status = int(result.get("status", 500))
        delete_not_found = operation["operation"] == "delete" and status == 404
        if not 200 <= status < 300 and not delete_not_found:
            failures.append({"itemIdentifier": operation["sequence_number"]})

    return {"batchItemFailures": failures}
