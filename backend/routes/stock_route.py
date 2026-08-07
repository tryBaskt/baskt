"""HTTP routes for stock metadata and performance analytics."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from starlette.status import HTTP_200_OK, HTTP_500_INTERNAL_SERVER_ERROR

from core.authentication import get_current_baskt_account
from core.deps import get_alpaca_broker_client, get_stock_analytics_service
from clients.alpaca_broker_client import AlpacaBrokerClient
from domain.baskt_account_domain import BasktAccount
from schema.stock_schema import StockAnalyticsResponse, StockResponse
from services.stock_analytics_service import (
    StockAnalyticsInternalServerError,
    StockAnalyticsService,
)


router = APIRouter(tags=["stocks"])


def _raise_stock_http_exception(error: Exception) -> None:
    if isinstance(error, HTTPException):
        raise error
    if isinstance(error, StockAnalyticsInternalServerError):
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": str(error), "code": error.code},
        ) from error
    raise HTTPException(
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "message": f"Unexpected stock error: {error}",
            "code": "STOCK_UNEXPECTED_ERROR",
        },
    ) from error


@router.get("/stocks/{stock_id}", response_model=StockResponse, status_code=HTTP_200_OK)
def get_stock(
    stock_id: str,
    baskt_account: BasktAccount = Depends(get_current_baskt_account),
    alpaca_broker_client: AlpacaBrokerClient = Depends(get_alpaca_broker_client),
) -> StockResponse:
    """Return Alpaca stock metadata by Alpaca asset id."""
    try:
        stock = alpaca_broker_client.get_stock_by_asset_id(asset_id=stock_id)
        return StockResponse(
            symbol=stock.symbol,
            tradable=stock.tradable,
            fractionable=stock.fractionable,
            shortable=stock.shortable,
            marginable=stock.marginable,
            stock_id=stock.stock_id,
            stock_class=stock.stock_class,
        )
    except Exception as error:
        _raise_stock_http_exception(error)


@router.get("/stock-analytics/{symbol}", response_model=StockAnalyticsResponse, status_code=HTTP_200_OK)
def get_stock_analytics(
    symbol: str,
    baskt_account: BasktAccount = Depends(get_current_baskt_account),
    service: StockAnalyticsService = Depends(get_stock_analytics_service),
) -> StockAnalyticsResponse:
    """Return standard-period performance analytics for one stock symbol."""
    try:
        return StockAnalyticsResponse(
            root=service.get_stock_bars(symbol=symbol.upper())
        )
    except Exception as error:
        _raise_stock_http_exception(error)
