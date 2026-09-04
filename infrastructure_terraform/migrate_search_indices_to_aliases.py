#!/usr/bin/env python3
"""Migrate search indices from concrete names to alias-backed versioned indices."""

from __future__ import annotations

import argparse
import json
import subprocess
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


TARGETS = (
    {
        "logical_name": "{environment}-model-portfolios",
        "versioned_name": "{environment}-model-portfolios-v1",
        "settings": {"index": {"number_of_shards": "1", "number_of_replicas": "0"}},
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
    },
    {
        "logical_name": "{environment}-baskt-accounts",
        "versioned_name": "{environment}-baskt-accounts-v1",
        "settings": {
            "index": {
                "number_of_shards": "1",
                "number_of_replicas": "0",
                "analysis": {
                    "normalizer": {
                        "lowercase_normalizer": {
                            "type": "custom",
                            "filter": ["lowercase"],
                        }
                    }
                },
            }
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
    },
)


class OpenSearchRequestError(Exception):
    """Raised when OpenSearch returns an unexpected response."""

    def __init__(self, method: str, path: str, status: int, body: str) -> None:
        super().__init__(f"{method} {path} failed with HTTP {status}: {body}")
        self.status = status
        self.body = body


def _domain_endpoint(session: boto3.Session, environment: str, region: str) -> str:
    domain_name = f"{environment}-model-portfolio-search"
    domain = session.client("opensearch", region_name=region).describe_domain(
        DomainName=domain_name
    )["DomainStatus"]
    endpoint = domain.get("Endpoint")
    if endpoint is None:
        endpoints = domain.get("Endpoints", {})
        endpoint = endpoints.get("vpc") or endpoints.get("dualstack")
    if endpoint is None:
        raise RuntimeError(f"OpenSearch domain {domain_name} has no endpoint")
    return f"https://{endpoint}"


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


def _request(
    *,
    session: boto3.Session,
    endpoint: str,
    region: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    ok_statuses: set[int] | None = None,
) -> tuple[int, dict[str, Any] | None]:
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    ok_statuses = ok_statuses or {200}
    encoded_body = json.dumps(body).encode("utf-8") if body is not None else None
    url = f"{endpoint}/{path.lstrip('/')}"
    credentials = session.get_credentials()
    if credentials is None:
        raise RuntimeError("AWS credentials are unavailable")

    aws_request = AWSRequest(
        method=method,
        url=url,
        data=encoded_body,
        headers={"Content-Type": "application/json"},
    )
    SigV4Auth(credentials.get_frozen_credentials(), "es", region).add_auth(aws_request)
    request = Request(
        url=url,
        data=encoded_body,
        headers=dict(aws_request.headers),
        method=method,
    )

    try:
        with urlopen(request, timeout=60) as response:
            response_body = response.read().decode("utf-8")
            return response.status, json.loads(response_body) if response_body else None
    except HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        if error.code in ok_statuses:
            return error.code, json.loads(response_body) if response_body else None
        raise OpenSearchRequestError(method, path, error.code, response_body) from error


def _exists(
    *,
    session: boto3.Session,
    endpoint: str,
    region: str,
    path: str,
) -> bool:
    status, _ = _request(
        session=session,
        endpoint=endpoint,
        region=region,
        method="HEAD",
        path=path,
        ok_statuses={200, 404},
    )
    return status == 200


def migrate_target(
    *,
    session: boto3.Session,
    endpoint: str,
    region: str,
    logical_name: str,
    versioned_name: str,
    settings: dict[str, Any],
    mappings: dict[str, Any],
    assume_yes: bool,
) -> None:
    alias_exists = _exists(
        session=session,
        endpoint=endpoint,
        region=region,
        path=f"_alias/{logical_name}",
    )
    if alias_exists:
        print(f"{logical_name} is already an alias; leaving it in place")
        return

    concrete_exists = _exists(
        session=session,
        endpoint=endpoint,
        region=region,
        path=logical_name,
    )
    versioned_exists = _exists(
        session=session,
        endpoint=endpoint,
        region=region,
        path=versioned_name,
    )

    if not versioned_exists:
        print(f"Creating {versioned_name}")
        _request(
            session=session,
            endpoint=endpoint,
            region=region,
            method="PUT",
            path=versioned_name,
            body={"settings": settings, "mappings": mappings},
            ok_statuses={200},
        )

    if concrete_exists:
        print(f"Copying documents from {logical_name} to {versioned_name}")
        _request(
            session=session,
            endpoint=endpoint,
            region=region,
            method="POST",
            path="_reindex?wait_for_completion=true&refresh=true",
            body={
                "source": {"index": logical_name},
                "dest": {"index": versioned_name},
                "conflicts": "proceed",
            },
            ok_statuses={200},
        )
        if not assume_yes:
            answer = input(
                f"Delete concrete index {logical_name} and replace it with an alias? "
                "Type the exact index name to continue: "
            )
            if answer != logical_name:
                raise RuntimeError(f"Did not delete {logical_name}; migration stopped")
        print(f"Deleting concrete index {logical_name}")
        _request(
            session=session,
            endpoint=endpoint,
            region=region,
            method="DELETE",
            path=logical_name,
            ok_statuses={200},
        )

    print(f"Creating alias {logical_name} -> {versioned_name}")
    _request(
        session=session,
        endpoint=endpoint,
        region=region,
        method="POST",
        path="_aliases",
        body={
            "actions": [
                {
                    "add": {
                        "index": versioned_name,
                        "alias": logical_name,
                        "is_write_index": True,
                    }
                }
            ]
        },
        ok_statuses={200},
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Move search indices behind stable OpenSearch aliases."
    )
    parser.add_argument("--environment", required=True, choices=("dev", "test", "stage", "prod"))
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument(
        "--profile",
        help="Optional AWS profile for local runs. Omit in GitHub Actions.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Delete same-named concrete indices without an interactive prompt.",
    )
    args = parser.parse_args()

    session = _session(args.profile, args.region)
    endpoint = _domain_endpoint(session, args.environment, args.region)

    for target in TARGETS:
        migrate_target(
            session=session,
            endpoint=endpoint,
            region=args.region,
            logical_name=target["logical_name"].format(environment=args.environment),
            versioned_name=target["versioned_name"].format(environment=args.environment),
            settings=target["settings"],
            mappings=target["mappings"],
            assume_yes=args.yes,
        )

    print("Search index alias migration complete.")


if __name__ == "__main__":
    main()
