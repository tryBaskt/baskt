"""Search services for model portfolios and, eventually, stocks."""

from __future__ import annotations

from typing import Any, Dict, List, TypedDict

from alpaca.trading.models import Asset

from clients.alpaca_broker_client import AlpacaBrokerClient, AlpacaBrokerClientError
from clients.opensearch_client import OpenSearchClient, OpenSearchClientError
from domain.model_portfolio_domain import ModelPortfolioOpenSearchResult, ModelPortfoliosOpenSearchResult
from domain.stock_domain import StockSearchResult, StocksSearchResult


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

    def __init__(
        self,
        *,
        opensearch_client: OpenSearchClient,
        alpaca_broker_client: AlpacaBrokerClient,
    ) -> None:
        """Initialize the search service.

        Args:
            opensearch_client: Client used to search indexed model portfolio metadata.
            alpaca_broker_client: Client used to look up stocks by symbol.

        Returns:
            None.
        """
        self.opensearch_client = opensearch_client
        self.alpaca_broker_client = alpaca_broker_client


    def search_model_portfolios_and_stocks(
        self,
        *,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> Any:
        """Search model portfolios and stocks using the same query.

        Args:
            query: Search text entered by the user.
            limit: Maximum number of model portfolios to return.
            offset: Number of matching model portfolios to skip.

        Returns:
            ModelPortfoliosStocksSearchResponse: Model portfolio search
            results and any exact stock-symbol match.

        Raises:
            ModelPortfoliosStocksSearchServiceError: If either underlying
                search operation fails.
        """
        return {
            "model_portfolios_opensearch_result": self.search_model_portfolios(
                query=query,
                limit=limit,
                offset=offset,
            ),
            "stocks_search_result": self.search_stocks(query=query),
        }


    def search_stocks(
        self,
        *,
        query: str,
    ) -> StocksSearchResult:
        """Search for a stock using an exact ticker symbol.

        Args:
            query: Exact stock ticker symbol entered by the user.

        Returns:
            List[StockSearchResult]: A one-item list when the stock exists,
            otherwise an empty list.

        Raises:
            ModelPortfoliosStocksSearchServiceError: If Alpaca fails while
                looking up the symbol or the returned asset cannot be parsed.
        """
        normalized_query = query.strip().upper()
        if not normalized_query:
            return []

        try:
            asset: Asset | None = self.alpaca_broker_client.get_stocks_by_symbol(
                symbol=normalized_query
            )
            if asset is None:
                return []

            return [
                StockSearchResult(
                    stock_id=str(asset.id),
                    symbol=str(asset.symbol),
                    tradable=bool(asset.tradable),
                    marginable=bool(asset.marginable),
                    shortable=bool(asset.shortable),
                    fractionable=bool(asset.fractionable),
                    stock_class=str(
                        getattr(asset.asset_class, "value", asset.asset_class)
                    ),
                )
            ]
        except AlpacaBrokerClientError as error:
            raise ModelPortfoliosStocksSearchServiceError(
                message=f"Failed to search stocks for symbol '{normalized_query}': {error}",
                code="STOCKS_SEARCH_ALPACA_FAILED",
            ) from error
        except (AttributeError, TypeError, ValueError) as error:
            raise ModelPortfoliosStocksSearchServiceError(
                message=f"Failed to parse stock search result for symbol '{normalized_query}': {error}",
                code="STOCKS_SEARCH_RESPONSE_INVALID",
            ) from error

    def search_model_portfolios(
        self,
        *,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> ModelPortfoliosOpenSearchResult:
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
            return ModelPortfoliosOpenSearchResult(
                model_portfolios=[],
                total=0,
                limit=limit,
                offset=offset,
            )

        try:
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
                                        "query": normalized_query,
                                        "boost": 4,
                                    }
                                }
                            },
                            {
                                "multi_match": {
                                    "query": normalized_query,
                                    "fields": [
                                        "portfolio_name^3",
                                        "description",
                                    ],
                                    "fuzziness": "AUTO",
                                }
                            },
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "sort": [
                    "_score",
                    {
                        "updated_at": {
                            "order": "desc",
                            "unmapped_type": "date",
                        }
                    },
                ],
            }
            response = self.opensearch_client.search(
                body=search_body,
            )
            hits_data = response["hits"]
            total_data = hits_data["total"]
            total = int(
                total_data["value"] if isinstance(total_data, dict) else total_data
            )
            model_portfolios: List[ModelPortfolioOpenSearchResult] = []
            for hit in hits_data["hits"]:
                source: Dict[str, Any] = hit["_source"]
                model_portfolios.append(
                    ModelPortfolioOpenSearchResult(
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
            return ModelPortfoliosOpenSearchResult(
                model_portfolios=model_portfolios,
                total=total,
                limit=limit,
                offset=offset
            )
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
