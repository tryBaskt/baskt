"""Search services for model portfolios and, eventually, stocks."""

from __future__ import annotations

from typing import Any, Dict, List, TypedDict

from clients.opensearch_client import OpenSearchClient, OpenSearchClientError


class ModelPortfolioSearchResult(TypedDict, total=False):
    """Searchable model portfolio metadata returned to callers."""

    portfolio_id: str
    portfolio_name: str
    description: str | None
    portfolio_owner_cognito_user_id: str
    created_at: str
    updated_at: str
    visibility: str
    score: float | None


class ModelPortfoliosSearchResponse(TypedDict):
    """Paginated model portfolio search response."""

    model_portfolios: List[ModelPortfolioSearchResult]
    total: int
    limit: int
    offset: int


class ModelPortfoliosStocksSearchServiceError(Exception):
    """Raised when model portfolio or stock search operations fail."""

    def __init__(self, message: str, code: str) -> None:
        """Initialize a search service exception.

        Args:
            message: Human-readable failure details.
            code: Stable application error code for the failed operation.

        Returns:
            None.
        """
        super().__init__(message)
        self.code = code


class ModelPortfoliosStocksSearchService:
    """Coordinate searches across model portfolios and stocks."""

    def __init__(self, *, opensearch_client: OpenSearchClient) -> None:
        """Initialize the search service.

        Args:
            opensearch_client: Client used to search indexed model portfolio metadata.

        Returns:
            None.
        """
        self.opensearch_client = opensearch_client

    def search_model_portfolios(
        self,
        *,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> ModelPortfoliosSearchResponse:
        """Search model portfolios by portfolio name or description.

        Name-prefix and name matches receive more relevance weight than
        description matches. Minor spelling errors are supported by
        OpenSearch fuzzy matching.

        Args:
            query: Search text entered by the user.
            limit: Maximum number of model portfolios to return, from 1 through 50.
            offset: Number of matching model portfolios to skip for pagination.

        Returns:
            ModelPortfoliosSearchResponse: Matching model portfolio metadata and pagination
            information. A blank query returns an empty result set.

        Raises:
            ModelPortfoliosStocksSearchServiceError: If pagination arguments are invalid,
                OpenSearch fails, or its response cannot be parsed.
        """
        normalized_query = query.strip()
        if not 1 <= limit <= 50:
            raise ModelPortfoliosStocksSearchServiceError(
                message="Model portfolio search limit must be between 1 and 50",
                code="MODEL_PORTFOLIOS_SEARCH_INVALID_LIMIT",
            )
        if offset < 0:
            raise ModelPortfoliosStocksSearchServiceError(
                message="Model portfolio search offset cannot be negative",
                code="MODEL_PORTFOLIOS_SEARCH_INVALID_OFFSET",
            )
        if not normalized_query:
            return {
                "model_portfolios": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
            }

        try:
            response = self.opensearch_client.search_model_portfolios(
                query=normalized_query,
                limit=limit,
                offset=offset,
            )
            hits_data = response["hits"]
            total_data = hits_data["total"]
            total = int(
                total_data["value"] if isinstance(total_data, dict) else total_data
            )
            model_portfolios: List[ModelPortfolioSearchResult] = []
            for hit in hits_data["hits"]:
                source: Dict[str, Any] = hit["_source"]
                model_portfolios.append(
                    ModelPortfolioSearchResult(
                        portfolio_id=str(source["portfolio_id"]),
                        portfolio_name=str(source["portfolio_name"]),
                        description=source.get("description"),
                        portfolio_owner_cognito_user_id=str(
                            source["portfolio_owner_cognito_user_id"]
                        ),
                        created_at=str(source["created_at"]),
                        updated_at=str(source["updated_at"]),
                        visibility=source.get("visibility"),
                        score=(
                            float(hit["_score"])
                            if hit.get("_score") is not None
                            else None
                        ),
                    )
                )
            return {
                "model_portfolios": model_portfolios,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        except OpenSearchClientError as error:
            raise ModelPortfoliosStocksSearchServiceError(
                message=f"Failed to search model portfolios for query '{normalized_query}': {error}",
                code="MODEL_PORTFOLIOS_SEARCH_OPENSEARCH_FAILED",
            ) from error
        except (KeyError, TypeError, ValueError) as error:
            raise ModelPortfoliosStocksSearchServiceError(
                message=f"Failed to parse model portfolio search results: {error}",
                code="MODEL_PORTFOLIOS_SEARCH_RESPONSE_INVALID",
            ) from error
