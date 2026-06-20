"""IAM-authenticated client for Baskt OpenSearch operations."""

from __future__ import annotations

import json
from typing import Any, Dict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.exceptions import BotoCoreError, ClientError


class OpenSearchClientError(Exception):
    """Raised when an OpenSearch operation fails."""

    def __init__(self, message: str, code: str) -> None:
        """Initialize an OpenSearch client exception.

        Args:
            message: Human-readable failure details.
            code: Stable application error code for the failed operation.

        Returns:
            None.
        """
        super().__init__(message)
        self.code = code


class OpenSearchClient:
    """Perform signed requests against a managed OpenSearch domain."""

    def __init__(
        self,
        *,
        session: boto3.Session,
        region: str,
        domain_name: str,
        model_portfolio_index: str,
    ) -> None:
        """Initialize an OpenSearch client.

        Args:
            session: Boto3 session supplying AWS credentials.
            region: AWS region containing the OpenSearch domain.
            domain_name: Managed OpenSearch domain name.
            model_portfolio_index: Index containing searchable Baskt metadata.

        Returns:
            None.
        """
        self.session = session
        self.region = region
        self.domain_name = domain_name
        self.model_portfolio_index = model_portfolio_index
        self._endpoint: str | None = None

    def _get_endpoint(self) -> str:
        """Resolve and cache the managed OpenSearch HTTPS endpoint.

        Returns:
            str: OpenSearch domain endpoint beginning with ``https://``.

        Raises:
            OpenSearchClientError: If the domain cannot be described or has no
                available endpoint.
        """
        if self._endpoint is not None:
            return self._endpoint

        try:
            domain = self.session.client(
                "opensearch", region_name=self.region
            ).describe_domain(DomainName=self.domain_name)["DomainStatus"]
            endpoint = domain.get("Endpoint")
            if endpoint is None:
                endpoints = domain.get("Endpoints", {})
                endpoint = endpoints.get("vpc") or endpoints.get("dualstack")
            if endpoint is None:
                raise OpenSearchClientError(
                    message=f"OpenSearch domain '{self.domain_name}' has no endpoint",
                    code="OPENSEARCH_DOMAIN_ENDPOINT_NOT_FOUND",
                )
            self._endpoint = f"https://{endpoint}"
            return self._endpoint
        except OpenSearchClientError:
            raise
        except (BotoCoreError, ClientError, KeyError) as error:
            raise OpenSearchClientError(
                message=f"Failed to resolve OpenSearch domain '{self.domain_name}': {error}",
                code="OPENSEARCH_DESCRIBE_DOMAIN_FAILED",
            ) from error

    def _request(
        self,
        *,
        method: str,
        path: str,
        body: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Send an IAM-signed request to OpenSearch.

        Args:
            method: HTTP method used for the request.
            path: OpenSearch API path relative to the domain endpoint.
            body: Optional JSON request body.

        Returns:
            Dict[str, Any]: Decoded OpenSearch response body.

        Raises:
            OpenSearchClientError: If credentials are unavailable, OpenSearch
                rejects the request, or the network response is invalid.
        """
        endpoint = self._get_endpoint()
        url = f"{endpoint}/{path.lstrip('/')}"
        encoded_body = json.dumps(body).encode("utf-8") if body is not None else None
        credentials = self.session.get_credentials()
        if credentials is None:
            raise OpenSearchClientError(
                message="AWS credentials are unavailable for OpenSearch request",
                code="OPENSEARCH_CREDENTIALS_NOT_FOUND",
            )

        aws_request = AWSRequest(
            method=method,
            url=url,
            data=encoded_body,
            headers={"Content-Type": "application/json"},
        )
        SigV4Auth(
            credentials.get_frozen_credentials(), "es", self.region
        ).add_auth(aws_request)
        request = Request(
            url=url,
            data=encoded_body,
            headers=dict(aws_request.headers),
            method=method,
        )

        try:
            with urlopen(request, timeout=20) as response:
                response_body = response.read().decode("utf-8")
                return json.loads(response_body) if response_body else {}
        except HTTPError as error:
            response_body = error.read().decode("utf-8", errors="replace")
            raise OpenSearchClientError(
                message=(
                    f"OpenSearch request to '{path}' failed with HTTP "
                    f"{error.code}: {response_body}"
                ),
                code="OPENSEARCH_HTTP_REQUEST_FAILED",
            ) from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise OpenSearchClientError(
                message=f"OpenSearch request to '{path}' failed: {error}",
                code="OPENSEARCH_REQUEST_FAILED",
            ) from error

    def search_model_portfolios(
        self,
        *,
        query: str,
        limit: int,
        offset: int,
    ) -> Dict[str, Any]:
        """Search Baskt names and descriptions.

        Args:
            query: User-provided search text.
            limit: Maximum number of matching Baskts to return.
            offset: Number of matching Baskts to skip.

        Returns:
            Dict[str, Any]: Raw OpenSearch search response.

        Raises:
            OpenSearchClientError: If the signed OpenSearch request fails.
        """
        search_body = {
            "from": offset,
            "size": limit,
            "track_total_hits": True,
            "_source": [
                "portfolio_id",
                "portfolio_name",
                "description",
                "portfolio_owner_cognito_user_id",
                "created_at",
                "updated_at",
                "visibility",
            ],
            "query": {
                "bool": {
                    "should": [
                        {
                            "match_phrase_prefix": {
                                "portfolio_name": {
                                    "query": query,
                                    "boost": 4,
                                }
                            }
                        },
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["portfolio_name^3", "description"],
                                "fuzziness": "AUTO",
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                }
            },
            "sort": [
                "_score",
                {"updated_at": {"order": "desc", "unmapped_type": "date"}},
            ],
        }
        return self._request(
            method="POST",
            path=f"{self.model_portfolio_index}/_search",
            body=search_body,
        )
