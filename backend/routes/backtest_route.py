# backend/api/routes/backtest.py

# Python imports
from __future__ import annotations
from datetime import date
import json
from typing import Any, Dict, List, Type

# Fastapi imports
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError

# Baskt imports
from core.deps import get_backtest_service, get_current_user
from schema.backtest_schema import BacktestPositionRequest, BasktAssetResponse, BasktAssetsResponse, BacktestResponse
from services.backtest_service import (BacktestService, 
                                       BacktestServiceCalculationError,
                                       BacktestServiceError,
                                       BacktestServiceDataError,
                                       BacktestServiceValidationError)
                                        


router = APIRouter(prefix="/backtest", tags=["backtest"])


BACKTEST_ERROR_STATUS_MAP: tuple[tuple[Type[Exception], int], ...] = (
    (ValueError, status.HTTP_400_BAD_REQUEST),
    (json.JSONDecodeError, status.HTTP_400_BAD_REQUEST),
    (BacktestServiceValidationError, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (BacktestServiceDataError, status.HTTP_502_BAD_GATEWAY),
    (BacktestServiceCalculationError, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (BacktestServiceError, status.HTTP_500_INTERNAL_SERVER_ERROR),
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
            code = err.code if isinstance(err, BacktestServiceError) else "BACKTEST_INVALID_REQUEST"
            raise HTTPException(
                status_code=status_code,
                detail={"message": str(err), "code": code},
            ) from err

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"message": f"Unexpected backtest error: {err}", "code": "BACKTEST_UNEXPECTED_ERROR"},
    ) from err


def _parse_positions_query(positions: str) -> List[Dict[str, Any]]:
    """
    Parse and validate JSON-encoded backtest positions from the query string.

    Args:
        positions: JSON-encoded list of backtest position objects.

    Returns:
        List[Dict[str, Any]]: Validated position dictionaries for the service.

    Raises:
        ValueError: If positions is not a JSON list.
        json.JSONDecodeError: If positions is not valid JSON.
        BacktestServiceValidationError: If any position does not match the
        request schema.
    """
    positions_conf = json.loads(positions)
    if not isinstance(positions_conf, list):
        raise ValueError("positions must be a JSON list")

    try:
        return [
            BacktestPositionRequest.model_validate(position).model_dump(exclude_none=True)
            for position in positions_conf
        ]
    except ValidationError as err:
        raise BacktestServiceValidationError(
            message=f"Invalid backtest position configuration: {err}"
        ) from err


@router.get("/tradeable-fractionable-us-baskt-assets", response_model=BasktAssetsResponse)
def get_tradeable_fractionable_us_baskt_assets(
    backtest_service: BacktestService = Depends(get_backtest_service),
    user: Dict[str, Any] = Depends(get_current_user)
) -> BasktAssetsResponse:
    """
    Get active US equity assets that Baskt can trade fractionally.

    Args:
        backtest_service: Service dependency that fetches Alpaca assets.
        user: Authenticated user from dependency injection.

    Returns:
        BasktAssetsResponse: List of tradable, fractionable US Baskt assets.

    Raises:
        HTTPException: If the service fails to fetch assets.
    """
    try:
        baskt_assets = backtest_service.get_tradeable_fractionable_US_baskt_assets()
        return BasktAssetsResponse(
            baskt_assets=[
                BasktAssetResponse(
                    symbol=baskt_asset.symbol,
                    tradable=baskt_asset.tradable,
                    fractionable=baskt_asset.fractionable,
                    asset_class=baskt_asset.asset_class
                )
                for baskt_asset in baskt_assets
            ]
        )
    except Exception as err:
        _raise_backtest_http_exception(err)


@router.get("", response_model=BacktestResponse)
def backtest(
    start_date: date,
    end_date: date,
    positions: str,
    user=Depends(get_current_user),
    svc: BacktestService = Depends(get_backtest_service),
) -> BacktestResponse:
    """
    Run a portfolio backtest for a date range and return timeseries + summary metrics.

    Args:
        start_date: Inclusive backtest start date (YYYY-MM-DD).
        end_date: Inclusive backtest end date (YYYY-MM-DD).
        positions: JSON-encoded list of position configs. Each item should contain:
            - symbol (str): ticker symbol
            - weight (float): portfolio weight fraction (0..1), or
              target_weight (float): portfolio weight as a percent or fraction
            - direction (int): +1 for long, -1 for short
            - leverage (float/int, optional): leverage multiplier; defaults to 1 if omitted
        user: Authenticated user from dependency injection; used for access control.
        svc: BacktestService dependency that performs the backtest computation.

        Returns:
        BacktestResponse: Dates, cumulative returns, and summary metrics.

    Raises:
        HTTPException: If request validation, data retrieval, or backtest
        calculation fails.
    """
    try:
        positions_conf = _parse_positions_query(positions)
        result = svc.run_backtest(
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            positions_conf=positions_conf
        )
        return BacktestResponse(**result)

    except Exception as e:
        _raise_backtest_http_exception(e)
