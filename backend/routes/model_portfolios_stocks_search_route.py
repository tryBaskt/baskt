"""HTTP routes for searching model portfolios and stocks."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette import status

from core.deps import get_current_user, get_model_portfolios_stocks_search_service
from schema.model_portfolios_stocks_search_schema import (
    ModelPortfolioSearchResultResponse,
    ModelPortfoliosSearchResponse,
)
from services.model_portfolios_stocks_search_service import (
    ModelPortfoliosStocksSearchService,
    ModelPortfoliosStocksSearchServiceError,
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

    if isinstance(error, ModelPortfoliosStocksSearchServiceError):
        invalid_request_codes = {
            "MODEL_PORTFOLIOS_SEARCH_INVALID_LIMIT",
            "MODEL_PORTFOLIOS_SEARCH_INVALID_OFFSET",
        }
        status_code = (
            status.HTTP_422_UNPROCESSABLE_ENTITY
            if error.code in invalid_request_codes
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(status_code=status_code, detail=str(error)) from error

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Unexpected model portfolio search error: {error}",
    ) from error


@router.get(
    "/model-portfolios",
    response_model=ModelPortfoliosSearchResponse,
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
) -> ModelPortfoliosSearchResponse:
    """Search model portfolios by portfolio name or description.

    Args:
        query: Search text supplied by the authenticated user.
        limit: Maximum number of matching model portfolios to return.
        offset: Number of matching model portfolios to skip for pagination.
        user: Authenticated Cognito claims resolved by dependency injection.
        service: Model portfolio and stock search service dependency.

    Returns:
        ModelPortfoliosSearchResponse: Matching model portfolios and pagination metadata.

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
        return ModelPortfoliosSearchResponse(
            model_portfolios=[
                ModelPortfolioSearchResultResponse(**model_portfolio)
                for model_portfolio in search_response["model_portfolios"]
            ],
            total=search_response["total"],
            limit=search_response["limit"],
            offset=search_response["offset"],
        )
    except Exception as error:
        _raise_search_http_exception(error)
