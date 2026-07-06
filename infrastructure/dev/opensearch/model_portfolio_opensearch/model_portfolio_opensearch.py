#!/usr/bin/env python3
"""Create or destroy the dev OpenSearch domain and search indexes.

Usage:
    python model_portfolio_opensearch.py --create
    python model_portfolio_opensearch.py --destroy
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.exceptions import ClientError

sys.path.append(str(Path(__file__).resolve().parents[3]))
from aws_env import load_aws_env


load_aws_env()

REGION = "us-east-1"
DOMAIN_NAME = "dev-model-portfolio-search"
INDEX_NAME = "dev-model-portfolios"
BASKT_ACCOUNT_INDEX_NAME = "dev-baskt-accounts"
INSTANCE_TYPE = "t3.small.search"
VOLUME_SIZE_GIB = 10


def _account_id() -> str:
    """Return the AWS account ID associated with the actie credentials."""
    return boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]


def _domain_access_policy(account_id: str) -> str:
    """Build an IAM-only access policy for principals in this AWS account."""
    domain_arn = f"arn:aws:es:{REGION}:{account_id}:domain/{DOMAIN_NAME}/*"
    return json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": f"arn:aws:iam::{account_id}:root"},
                    "Action": "es:ESHttp*",
                    "Resource": domain_arn,
                }
            ],
        }
    )


def _describe_domain(opensearch: Any) -> Dict[str, Any] | None:
    """Return the domain status, or None when the domain does not exist."""
    try:
        return opensearch.describe_domain(DomainName=DOMAIN_NAME)["DomainStatus"]
    except opensearch.exceptions.ResourceNotFoundException:
        return None


def _wait_for_domain(opensearch: Any, timeout_seconds: int = 3600) -> Dict[str, Any]:
    """Wait until the domain is active and return its status."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        domain = _describe_domain(opensearch)
        if domain and not domain.get("Processing") and not domain.get("UpgradeProcessing"):
            return domain
        time.sleep(30)
    raise TimeoutError(f"Timed out waiting for OpenSearch domain '{DOMAIN_NAME}'")


def _wait_for_deletion(opensearch: Any, timeout_seconds: int = 3600) -> None:
    """Wait until the domain no longer exists."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _describe_domain(opensearch) is None:
            return
        time.sleep(30)
    raise TimeoutError(f"Timed out deleting OpenSearch domain '{DOMAIN_NAME}'")


def _domain_endpoint(domain: Dict[str, Any]) -> str:
    """Return the domain's HTTPS endpoint."""
    endpoint = domain.get("Endpoint")
    if endpoint is None:
        endpoints = domain.get("Endpoints", {})
        endpoint = endpoints.get("vpc") or endpoints.get("dualstack")
    if endpoint is None:
        raise RuntimeError(f"OpenSearch domain '{DOMAIN_NAME}' has no endpoint")
    return f"https://{endpoint}"


def _signed_request(
    method: str,
    endpoint: str,
    path: str,
    body: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Send an IAM-signed request to the OpenSearch data endpoint."""
    url = f"{endpoint.rstrip('/')}/{path.lstrip('/')}"
    encoded_body = json.dumps(body).encode("utf-8") if body is not None else None
    credentials = boto3.Session().get_credentials()
    if credentials is None:
        raise RuntimeError("Could not obtain AWS credentials for OpenSearch request")

    aws_request = AWSRequest(
        method=method,
        url=url,
        data=encoded_body,
        headers={"Content-Type": "application/json"},
    )
    SigV4Auth(credentials.get_frozen_credentials(), "es", REGION).add_auth(
        aws_request
    )
    request = Request(
        url=url,
        data=encoded_body,
        headers=dict(aws_request.headers),
        method=method,
    )
    try:
        with urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8")
            return json.loads(response_body) if response_body else {}
    except HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        try:
            error_payload = json.loads(response_body)
        except json.JSONDecodeError:
            error_payload = {"message": response_body}
        raise OpenSearchRequestError(error.code, error_payload) from error


class OpenSearchRequestError(RuntimeError):
    """Represent an unsuccessful OpenSearch data-plane request."""

    def __init__(self, status_code: int, payload: Dict[str, Any]) -> None:
        super().__init__(f"OpenSearch HTTP {status_code}: {payload}")
        self.status_code = status_code
        self.payload = payload


def _ensure_index(
    endpoint: str,
    index_name: str,
    index_configuration: Dict[str, Any],
) -> None:
    """Create an OpenSearch index if it does not already exist."""
    try:
        _signed_request("PUT", endpoint, index_name, index_configuration)
        print(f"Created OpenSearch index: {index_name}")
    except OpenSearchRequestError as error:
        error_details = error.payload.get("error", {})
        error_type = (
            error_details.get("type") if isinstance(error_details, dict) else None
        )
        if error.status_code == 400 and error_type == "resource_already_exists_exception":
            print(f"OpenSearch index already exists: {index_name}")
            return
        raise


def _model_portfolio_index_configuration() -> Dict[str, Any]:
    """Return the model portfolio search index mapping."""
    return {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        },
        "mappings": {
            "properties": {
                "portfolio_id": {"type": "keyword"},
                "portfolio_name": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword"}},
                },
                "description": {"type": "text"},
                "portfolio_owner_cognito_user_id": {"type": "keyword"},
                "created_at": {"type": "date"},
                "updated_at": {"type": "date"},
                "visibility": {"type": "keyword"},
            }
        },
    }


def _baskt_account_index_configuration() -> Dict[str, Any]:
    """Return the public Baskt account search index mapping."""
    return {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "analysis": {
                "normalizer": {
                    "lowercase_normalizer": {
                        "type": "custom",
                        "filter": ["lowercase"],
                    }
                }
            },
        },
        "mappings": {
            "properties": {
                "cognito_user_id": {"type": "keyword"},
                "display_name": {
                    "type": "text",
                    "fields": {
                        "keyword": {
                            "type": "keyword",
                            "normalizer": "lowercase_normalizer",
                        }
                    },
                },
                "description": {"type": "text"},
                "profile_image": {"type": "keyword", "index": False},
            }
        },
    }


def create_opensearch() -> None:
    """Create the dev domain and ensure its search index exists."""
    opensearch = boto3.client("opensearch", region_name=REGION)
    domain = _describe_domain(opensearch)

    if domain is None:
        account_id = _account_id()
        print(f"Creating OpenSearch domain: {DOMAIN_NAME}")
        opensearch.create_domain(
            DomainName=DOMAIN_NAME,
            ClusterConfig={
                "InstanceType": INSTANCE_TYPE,
                "InstanceCount": 1,
                "DedicatedMasterEnabled": False,
                "ZoneAwarenessEnabled": False,
                "WarmEnabled": False,
                "MultiAZWithStandbyEnabled": False,
            },
            EBSOptions={
                "EBSEnabled": True,
                "VolumeType": "gp3",
                "VolumeSize": VOLUME_SIZE_GIB,
            },
            AccessPolicies=_domain_access_policy(account_id),
            EncryptionAtRestOptions={"Enabled": True},
            NodeToNodeEncryptionOptions={"Enabled": True},
            DomainEndpointOptions={
                "EnforceHTTPS": True,
                "TLSSecurityPolicy": "Policy-Min-TLS-1-2-2019-07",
            },
            IPAddressType="ipv4",
            TagList=[
                {"Key": "Environment", "Value": "dev"},
                {"Key": "Application", "Value": "Baskt"},
                {"Key": "Purpose", "Value": "model-portfolio-search"},
            ],
        )
    else:
        print(f"OpenSearch domain already exists: {DOMAIN_NAME}")

    print("Waiting for the OpenSearch domain to become active...")
    domain = _wait_for_domain(opensearch)
    endpoint = _domain_endpoint(domain)
    _ensure_index(
        endpoint,
        INDEX_NAME,
        _model_portfolio_index_configuration(),
    )
    _ensure_index(
        endpoint,
        BASKT_ACCOUNT_INDEX_NAME,
        _baskt_account_index_configuration(),
    )

    print(f"OpenSearch domain: {DOMAIN_NAME}")
    print(f"OpenSearch endpoint: {endpoint}")
    print(f"Model portfolio OpenSearch index: {INDEX_NAME}")
    print(f"Baskt account OpenSearch index: {BASKT_ACCOUNT_INDEX_NAME}")


def destroy_opensearch() -> None:
    """Delete the dev OpenSearch domain and all indexes in it."""
    opensearch = boto3.client("opensearch", region_name=REGION)
    if _describe_domain(opensearch) is None:
        print(f"OpenSearch domain does not exist: {DOMAIN_NAME}")
        return

    print(f"Deleting OpenSearch domain: {DOMAIN_NAME}")
    opensearch.delete_domain(DomainName=DOMAIN_NAME)
    _wait_for_deletion(opensearch)
    print(f"Deleted OpenSearch domain: {DOMAIN_NAME}")


def main() -> None:
    """Parse the requested domain operation and execute it."""
    parser = argparse.ArgumentParser(
        description=f"Manage the dev OpenSearch domain '{DOMAIN_NAME}'."
    )
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--create", action="store_true", help="Create the domain")
    operation.add_argument("--destroy", action="store_true", help="Delete the domain")
    args = parser.parse_args()

    try:
        if args.create:
            create_opensearch()
        else:
            destroy_opensearch()
    except (ClientError, OpenSearchRequestError, RuntimeError, TimeoutError) as error:
        print(f"Failed to manage OpenSearch infrastructure: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
