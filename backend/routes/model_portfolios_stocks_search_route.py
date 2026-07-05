"""HTTP routes for searching model portfolios and stocks."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette import status

from core.deps import get_current_user, get_model_portfolios_stocks_search_service
from schema.model_portfolios_stocks_search_schema import (
    ModelPortfolioOpenSearchResultResponse,
    ModelPortfoliosOpenSearchResultResponse,
    ModelPortfoliosStocksOpenSearchResponse,
    StockSearchResultResponse,
    StocksSearchResultResponse,
)

from services.model_portfolios_stocks_search_service import (
    ModelPortfoliosStocksSearchInternalServerError,
    ModelPortfoliosStocksSearchService,
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

    if isinstance(error, ModelPortfoliosStocksSearchInternalServerError):
        invalid_request_codes = {
            "MODEL_PORTFOLIOS_SEARCH_INVALID_LIMIT",
            "MODEL_PORTFOLIOS_SEARCH_INVALID_OFFSET",
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
    response_model=ModelPortfoliosStocksOpenSearchResponse,
    status_code=status.HTTP_200_OK,
)
def search_model_portfolios_and_stocks(
    query: str = Query(min_length=1),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    user: Dict[str, Any] = Depends(get_current_user),
    service: ModelPortfoliosStocksSearchService = Depends(
        get_model_portfolios_stocks_search_service
    ),
) -> ModelPortfoliosStocksOpenSearchResponse:
    """Search model portfolios and stocks for an authenticated user.

    Args:
        query: Model portfolio text query and exact stock ticker symbol.
        limit: Maximum number of model portfolio matches to return.
        offset: Number of model portfolio matches to skip.
        user: Authenticated Cognito claims resolved by dependency injection.
        service: Model portfolio and stock search service dependency.

    Returns:
        ModelPortfoliosStocksOpenSearchResponse: Paginated model portfolio results
        and any exact stock-symbol match.

    Raises:
        HTTPException: If request validation or either search operation fails.
    """
    del user

    try:
        search_response = service.search_model_portfolios_and_stocks(
            query=query,
            limit=limit,
            offset=offset,
        )
        model_portfolios_response = search_response[
            "model_portfolios_opensearch_result"
        ]
        stocks_response = search_response["stocks_search_result"]
        return ModelPortfoliosStocksOpenSearchResponse(
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
        )
    except Exception as error:
        _raise_search_http_exception(error)


@router.get(
    "/model-portfolios",
    response_model=ModelPortfoliosOpenSearchResultResponse,
    status_code=status.HTTP_200_OK,
)
def search_model_portfolios(
    query: str = Query(min_length=1),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    user: Dict[str, Any] = Depends(get_current_user),
    service: ModelPortfoliosStocksSearchService = Depends(
        get_model_portfolios_stocks_search_service
    ),
) -> ModelPortfoliosOpenSearchResultResponse:
    """Search model portfolios by portfolio name or description.

    Args:
        query: Search text supplied by the authenticated user.
        limit: Maximum number of matching model portfolios to return.
        offset: Number of matching model portfolios to skip for pagination.
        user: Authenticated Cognito claims resolved by dependency injection.
        service: Model portfolio and stock search service dependency.

    Returns:
        ModelPortfoliosOpenSearchResultResponse: Matching model portfolios and pagination metadata.

    Raises:
        HTTPException: If search validation fails, OpenSearch is unavailable,
            its response is invalid, or an unexpected error occurs.
    """
    del user

    try:
        search_response = service.search_model_portfolios(
            query=query,
            limit=limit,
            offset=offset,
        )
        return ModelPortfoliosOpenSearchResultResponse(
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
                for model_portfolio in search_response.model_portfolios
            ],
            total=search_response.total,
            limit=search_response.limit,
            offset=search_response.offset,
        )
    except Exception as error:
        _raise_search_http_exception(error)
