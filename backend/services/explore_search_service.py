"""Search DynamoDB portfolio/profile metadata and Alpaca stock symbols."""

from __future__ import annotations

from typing import Any, Dict, List

from clients.alpaca_broker_client import AlpacaBrokerClient, AlpacaBrokerClientError
from domain.model_portfolio_domain import ModelPortfolioSearchResult, ModelPortfoliosSearchResult
from domain.stock_domain import Stock, StockSearchResult, StocksSearchResult
from domain.baskt_account_domain import BasktAccountSearchResult, BasktAccountsSearchResult
from repository.baskt_account_repository import (
    BasktAccountRepository,
    BasktAccountRepositoryError,
)
from repository.model_portfolio_repository import (
    ModelPortfolioRepository,
    ModelPortfolioInternalServerError,
)


class ExploreSearchInternalServerError(Exception):
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


def _match_score(query: str, name: str, description: str | None) -> float:
    """Rank exact names, prefixes, substrings, then description matches."""
    name = name.casefold()
    description = (description or "").casefold()
    if name == query:
        return 4.0
    if name.startswith(query):
        return 3.0
    if query in name:
        return 2.0
    if query in description:
        return 1.0
    if all(term in name or term in description for term in query.split()):
        return 1.0
    return 0.0


class ExploreSearchService:
    """Coordinate searches across model portfolios and stocks."""

    def __init__(
        self,
        *,
        model_portfolio_repository: ModelPortfolioRepository,
        alpaca_broker_client: AlpacaBrokerClient,
        baskt_account_repository: BasktAccountRepository,
    ) -> None:
        """Initialize the search service.

        Args:
            model_portfolio_repository: Repository for DynamoDB portfolio metadata.
            alpaca_broker_client: Client used to look up stocks by symbol.

        Returns:
            None.
        """
        self.model_portfolio_repository = model_portfolio_repository
        self.alpaca_broker_client = alpaca_broker_client
        self.baskt_account_repository = baskt_account_repository


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
            ExploreSearchResponse: Model portfolio search
            results and any exact stock-symbol match.

        Raises:
            ExploreSearchInternalServerError: If either underlying
                search operation fails.
        """
        return {
            "model_portfolios_search_result": self.search_model_portfolios(
                query=query,
                limit=limit,
                offset=offset,
            ),
            "stocks_search_result": self.search_stocks(query=query),
            "baskt_accounts_search_result": self.search_baskt_accounts(
                query=query,
                limit=limit,
                offset=offset,
            ),
        }

    def search_baskt_accounts(
        self,
        *,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> Any:
        """Search public Baskt accounts by display name or description."""
        normalized_query = query.strip()
        if not 1 <= limit <= 50:
            raise ExploreSearchInternalServerError(
                message="Baskt account search limit must be between 1 and 50",
                code="BASKT_ACCOUNT_SEARCH_INVALID_LIMIT",
            )
        if offset < 0:
            raise ExploreSearchInternalServerError(
                message="Baskt account search offset cannot be negative",
                code="BASKT_ACCOUNT_SEARCH_INVALID_OFFSET",
            )
        if not normalized_query:
            return BasktAccountsSearchResult(
                baskt_accounts=[],
                total=0,
                limit=limit,
                offset=offset
            )

        try:
            matches = []
            for item in self.baskt_account_repository.get_search_metadata():
                score = _match_score(
                    normalized_query.casefold(), item["display_name"], item.get("description")
                )
                if score:
                    matches.append((score, item))
            matches.sort(key=lambda match: (
                -match[0], match[1]["display_name"].casefold(), match[1]["cognito_user_id"],
            ))
            return BasktAccountsSearchResult(
                baskt_accounts=[
                    BasktAccountSearchResult(
                        cognito_user_id=item["cognito_user_id"],
                        display_name=item["display_name"],
                        description=item.get("description"),
                        profile_image=item.get("profile_image"),
                    )
                    for _, item in matches[offset:offset + limit]
                ],
                total=len(matches), limit=limit, offset=offset,
            )
        except BasktAccountRepositoryError as error:
            raise ExploreSearchInternalServerError(
                message=f"Failed to search Baskt accounts: {error}",
                code="BASKT_ACCOUNT_SEARCH_DYNAMODB_FAILED",
            ) from error
        except (KeyError, AttributeError, TypeError, ValueError) as error:
            raise ExploreSearchInternalServerError(
                message=f"Failed to parse Baskt account search results: {error}",
                code="BASKT_ACCOUNT_SEARCH_RESPONSE_INVALID",
            ) from error


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
            ExploreSearchInternalServerError: If Alpaca fails while
                looking up the symbol or the returned asset cannot be parsed.
        """
        normalized_query = query.strip().upper()
        if not normalized_query:
            return []

        try:
            stock: Stock | None = self.alpaca_broker_client.get_stock_by_symbol(
                symbol=normalized_query
            )
            if stock is None:
                return []

            return [
                StockSearchResult(
                    stock_id=stock.stock_id,
                    symbol=stock.symbol,
                    tradable=stock.tradable,
                    marginable=stock.marginable,
                    shortable=stock.shortable,
                    fractionable=stock.fractionable,
                    stock_class=stock.stock_class,
                )
            ]
        except AlpacaBrokerClientError as error:
            raise ExploreSearchInternalServerError(
                message=f"Failed to search stocks for symbol '{normalized_query}': {error}",
                code="STOCKS_SEARCH_ALPACA_FAILED",
            ) from error
        except (AttributeError, TypeError, ValueError) as error:
            raise ExploreSearchInternalServerError(
                message=f"Failed to parse stock search result for symbol '{normalized_query}': {error}",
                code="STOCKS_SEARCH_RESPONSE_INVALID",
            ) from error

    def search_model_portfolios(
        self,
        *,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> ModelPortfoliosSearchResult:
        """Search model portfolios by portfolio name or description.

        Matches are case-insensitive. Exact names and name prefixes rank above
        description matches. All DynamoDB scan pages are read before pagination.

        Args:
            query: Search text entered by the user.
            limit: Maximum number of model portfolios to return, from 1 through 50.
            offset: Number of matching model portfolios to skip for pagination.

        Returns:
            ModelPortfoliosSearchResponse: Matching model portfolio metadata and pagination
            information. A blank query returns an empty result set.

        Raises:
            ExploreSearchInternalServerError: If pagination arguments are invalid,
                DynamoDB fails, or its response cannot be parsed.
        """
        normalized_query = query.strip()
        if not 1 <= limit <= 50:
            raise ExploreSearchInternalServerError(
                message="Model portfolio search limit must be between 1 and 50",
                code="MODEL_PORTFOLIOS_SEARCH_INVALID_LIMIT",
            )
        if offset < 0:
            raise ExploreSearchInternalServerError(
                message="Model portfolio search offset cannot be negative",
                code="MODEL_PORTFOLIOS_SEARCH_INVALID_OFFSET",
            )
        if not normalized_query:
            return ModelPortfoliosSearchResult(
                model_portfolios=[],
                total=0,
                limit=limit,
                offset=offset,
            )

        try:
            matches = []
            for item in self.model_portfolio_repository.get_search_metadata():
                score = _match_score(
                    normalized_query.casefold(), item["portfolio_name"], item.get("description")
                )
                if score:
                    matches.append((score, item))
            # Stable tie breakers keep offset pages deterministic.
            matches.sort(key=lambda match: match[1]["portfolio_id"])
            matches.sort(key=lambda match: match[1]["updated_at"], reverse=True)
            matches.sort(key=lambda match: match[0], reverse=True)
            model_portfolios = []
            owner_display_names: Dict[str, str | None] = {}
            for score, source in matches[offset:offset + limit]:
                owner_cognito_user_id = source["portfolio_owner_cognito_user_id"]
                if owner_cognito_user_id not in owner_display_names:
                    try:
                        owner_display_names[owner_cognito_user_id] = (
                            self.baskt_account_repository.get_display_name(
                                cognito_user_id=owner_cognito_user_id
                            )
                        )
                    except BasktAccountRepositoryError:
                        owner_display_names[owner_cognito_user_id] = None
                model_portfolios.append(ModelPortfolioSearchResult(
                    portfolio_id=source["portfolio_id"],
                    portfolio_name=source["portfolio_name"],
                    description=source.get("description"),
                    portfolio_owner_cognito_user_id=owner_cognito_user_id,
                    portfolio_owner_display_name=owner_display_names[owner_cognito_user_id],
                    created_at=str(source["created_at"]),
                    updated_at=str(source["updated_at"]),
                    visibility=source.get("visibility"),
                    score=score,
                ))
            return ModelPortfoliosSearchResult(
                model_portfolios=model_portfolios,
                total=len(matches), limit=limit, offset=offset,
            )
        except ModelPortfolioInternalServerError as error:
            raise ExploreSearchInternalServerError(
                message=f"Failed to search model portfolios: {error}",
                code="MODEL_PORTFOLIOS_SEARCH_DYNAMODB_FAILED",
            ) from error
        except (KeyError, AttributeError, TypeError, ValueError) as error:
            raise ExploreSearchInternalServerError(
                message=f"Failed to parse model portfolio search results: {error}",
                code="MODEL_PORTFOLIOS_SEARCH_RESPONSE_INVALID",
            ) from error
