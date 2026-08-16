# backend/routes/backtest_analytics_route.py

# Python imports
from __future__ import annotations
from typing import Type

# Fastapi imports
from fastapi import APIRouter, Depends, HTTPException, status

# Baskt imports
from core.authentication import get_current_baskt_account
from core.deps import get_backtest_service
from domain.baskt_account_domain import BasktAccount
from schema.backtest_analytics_schema import BacktestAnalyticsResponse, BacktestRequest
from schema.stock_schema import StockResponse, StocksResponse
from services.backtest_analytics_service import (
    BacktestInternalServerError,
    BacktestService,
    BacktestServiceCalculationError,
    BacktestServiceDataError,
    BacktestServiceValidationError,
)

router = APIRouter(prefix="/backtest", tags=["backtest"])


BACKTEST_ERROR_STATUS_MAP: tuple[tuple[Type[Exception], int], ...] = (
    (ValueError, status.HTTP_400_BAD_REQUEST),
    (BacktestServiceValidationError, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (BacktestServiceDataError, status.HTTP_502_BAD_GATEWAY),
    (BacktestServiceCalculationError, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (BacktestInternalServerError, status.HTTP_500_INTERNAL_SERVER_ERROR),
)


def _raise_backtest_http_exception(err: Exception) -> None:
    """
    Convert backtest exceptions into FastAPI HTTP exceptions.

    Args:
        err: Exception raised by the route, service, or downstream clients.

    Returns:
        None.

    Raises:
        HTTPException: Always raises an HTTP exception matching the error type.
    """
    if isinstance(err, HTTPException):
        raise err

    for exception_type, status_code in BACKTEST_ERROR_STATUS_MAP:
        if isinstance(err, exception_type):
            code = err.code if isinstance(err, BacktestInternalServerError) else "BACKTEST_INVALID_REQUEST"
            raise HTTPException(
                status_code=status_code,
                detail={"message": str(err), "code": code},
            ) from err

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"message": f"Unexpected backtest error: {err}", "code": "BACKTEST_UNEXPECTED_ERROR"},
    ) from err


@router.get("/tradeable-fractionable-us-baskt-assets", response_model=StocksResponse)
def get_tradeable_fractionable_us_baskt_assets(
    backtest_service: BacktestService = Depends(get_backtest_service),
    baskt_account: BasktAccount = Depends(get_current_baskt_account)
) -> StocksResponse:
    """
    Get active US equity assets that Baskt can trade fractionally.

    Args:
        backtest_service: Service dependency that fetches Alpaca assets.
        user: Authenticated user from dependency injection.

    Returns:
        StocksResponse: List of tradable, fractionable US Baskt assets.

    Raises:
        HTTPException: If the service fails to fetch assets.
    """
    try:
        baskt_assets = backtest_service.get_tradeable_fractionable_US_baskt_assets()
        return StocksResponse(
            root=[
                StockResponse(
                    symbol=baskt_asset.symbol,
                    tradable=baskt_asset.tradable,
                    fractionable=baskt_asset.fractionable,
                    shortable=baskt_asset.shortable,
                    marginable=baskt_asset.marginable,
                    stock_id=baskt_asset.stock_id,
                    stock_class=baskt_asset.stock_class,
                )
                for baskt_asset in baskt_assets
            ]
        )
    except Exception as err:
        _raise_backtest_http_exception(err)


@router.post("", response_model=BacktestAnalyticsResponse)
def backtest(
    request: BacktestRequest,
    baskt_account: BasktAccount = Depends(get_current_baskt_account),
    svc: BacktestService = Depends(get_backtest_service),
) -> BacktestAnalyticsResponse:
    """
    Run a portfolio backtest for a date range and return timeseries + summary metrics.

    Args:
        request: Request body with date range and position configs.
        user: Authenticated user from dependency injection; used for access control.
        svc: BacktestService dependency that performs the backtest computation.

        Returns:
        BacktestAnalyticsResponse: Cumulative returns and summary metrics.

    Raises:
        HTTPException: If request validation, data retrieval, or backtest
        calculation fails.
    """
    try:
        result = svc.run_backtest(
            start_date=request.start_date.isoformat(),
            end_date=request.end_date.isoformat(),
            positions_conf=[
                position.model_dump(exclude_none=True)
                for position in request.positions
            ],
        )
        return BacktestAnalyticsResponse(**result)

    except Exception as e:
        _raise_backtest_http_exception(e)
