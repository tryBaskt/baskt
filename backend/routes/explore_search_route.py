"""HTTP routes for searching model portfolios and stocks."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette import status

from core.authentication import get_current_baskt_account
from core.deps import get_explore_search_service
from domain.baskt_account_domain import BasktAccount
from schema.explore_search_schema import (
    BasktAccountOpenSearchResultResponse,
    BasktAccountsOpenSearchResultResponse,
    ModelPortfolioOpenSearchResultResponse,
    ModelPortfoliosOpenSearchResultResponse,
    ExploreSearchOpenSearchResponse,
    StockSearchResultResponse,
    StocksSearchResultResponse,
)

from services.explore_search_service import (
    ExploreSearchInternalServerError,
    ExploreSearchService,
)


router = APIRouter(prefix="/search", tags=["search"])


def _raise_search_http_exception(error: Exception) -> None:
    """Convert search-layer exceptions into HTTP exceptions.

    Args:
        error: Exception raised while handling a search request.

    Returns:
        None.

    Raises:
        HTTPException: Always raised with the status corresponding to the
            search failure.
    """
    if isinstance(error, HTTPException):
        raise error

    if isinstance(error, ExploreSearchInternalServerError):
        invalid_request_codes = {
            "MODEL_PORTFOLIOS_SEARCH_INVALID_LIMIT",
            "MODEL_PORTFOLIOS_SEARCH_INVALID_OFFSET",
            "BASKT_ACCOUNT_SEARCH_INVALID_LIMIT",
            "BASKT_ACCOUNT_SEARCH_INVALID_OFFSET",
        }
        status_code = (
            status.HTTP_422_UNPROCESSABLE_CONTENT
            if error.code in invalid_request_codes
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=status_code,
            detail={"message": str(error), "code": error.code},
        ) from error

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "message": f"Unexpected model portfolio search error: {error}",
            "code": "MODEL_PORTFOLIOS_STOCKS_SEARCH_UNEXPECTED_ERROR",
        },
    ) from error


@router.get(
    "",
    response_model=ExploreSearchOpenSearchResponse,
    status_code=status.HTTP_200_OK,
)
def search_model_portfolios_and_stocks(
    query: str = Query(min_length=1),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    baskt_account: BasktAccount = Depends(get_current_baskt_account),
    service: ExploreSearchService = Depends(
        get_explore_search_service
    ),
) -> ExploreSearchOpenSearchResponse:
    """Search model portfolios and stocks for an authenticated user.

    Args:
        query: Model portfolio text query and exact stock ticker symbol.
        limit: Maximum number of model portfolio matches to return.
        offset: Number of model portfolio matches to skip.
        baskt_account: Authenticated Baskt account resolved by dependency
            injection.
        service: Model portfolio and stock search service dependency.

    Returns:
        ExploreSearchOpenSearchResponse: Paginated model portfolio results
        and any exact stock-symbol match.

    Raises:
        HTTPException: If request validation or either search operation fails.
    """
    try:
        del baskt_account
        search_response = service.search_model_portfolios_and_stocks(
            query=query,
            limit=limit,
            offset=offset,
        )
        model_portfolios_response = search_response[
            "model_portfolios_opensearch_result"
        ]
        stocks_response = search_response["stocks_search_result"]
        baskt_accounts_response = search_response[
            "baskt_accounts_opensearch_result"
        ]
        return ExploreSearchOpenSearchResponse(
            model_portfolios=ModelPortfoliosOpenSearchResultResponse(
                model_portfolios=[
                    ModelPortfolioOpenSearchResultResponse(
                        portfolio_id=model_portfolio.portfolio_id,
                        portfolio_name=model_portfolio.portfolio_name,
                        description=model_portfolio.description,
                        portfolio_owner_cognito_user_id=(
                            model_portfolio.portfolio_owner_cognito_user_id
                        ),
                        portfolio_owner_display_name=(
                            model_portfolio.portfolio_owner_display_name
                        ),
                        created_at=model_portfolio.created_at,
                        updated_at=model_portfolio.updated_at,
                        visibility=model_portfolio.visibility,
                        score=model_portfolio.score,
                    )
                    for model_portfolio in model_portfolios_response.model_portfolios
                ],
                total=model_portfolios_response.total,
                limit=model_portfolios_response.limit,
                offset=model_portfolios_response.offset,
            ),
            stocks=StocksSearchResultResponse(
                root=[
                    StockSearchResultResponse(
                        stock_id=stock.stock_id,
                        symbol=stock.symbol,
                        tradable=stock.tradable,
                        marginable=stock.marginable,
                        shortable=stock.shortable,
                        fractionable=stock.fractionable,
                        stock_class=stock.stock_class,
                    )
                    for stock in stocks_response
                ]
            ),
            baskt_accounts=BasktAccountsOpenSearchResultResponse(
                baskt_accounts=[
                    BasktAccountOpenSearchResultResponse(
                        cognito_user_id=account.cognito_user_id,
                        display_name=account.display_name,
                        description=account.description,
                        profile_image=account.profile_image,
                    )
                    for account in baskt_accounts_response.baskt_accounts
                ],
                total=baskt_accounts_response.total,
                limit=baskt_accounts_response.limit,
                offset=baskt_accounts_response.offset,
            ),
        )
    except Exception as error:
        _raise_search_http_exception(error)
