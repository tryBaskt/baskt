"""HTTP routes for stock performance analytics."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from starlette.status import HTTP_200_OK, HTTP_500_INTERNAL_SERVER_ERROR

from core.deps import get_current_user, get_stock_analytics_service
from schema.stock_schema import StockAnalyticsResponse
from services.stock_analytics_service import (
    StockAnalyticsService,
    StockAnalyticsServiceError,
)


router = APIRouter(prefix="/stock-analytics", tags=["stock-analytics"])


def _raise_stock_analytics_http_exception(error: Exception) -> None:
    if isinstance(error, HTTPException):
        raise error
    if isinstance(error, StockAnalyticsServiceError):
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(error),
        ) from error
    raise HTTPException(
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Unexpected stock analytics error: {error}",
    ) from error


@router.get("/{symbol}", response_model=StockAnalyticsResponse, status_code=HTTP_200_OK)
def get_stock_analytics(
    symbol: str,
    _user: Dict[str, Any] = Depends(get_current_user),
    service: StockAnalyticsService = Depends(get_stock_analytics_service),
) -> StockAnalyticsResponse:
    """Return standard-period performance analytics for one stock symbol."""
    try:
        return StockAnalyticsResponse(
            root=service.get_stock_bars(symbol=symbol.upper())
        )
    except Exception as error:
        _raise_stock_analytics_http_exception(error)
