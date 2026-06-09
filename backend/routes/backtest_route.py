# backend/api/routes/backtest.py

# Python imports
from __future__ import annotations
from datetime import date
import json
from typing import Any, Dict, Type

# Fastapi imports
from fastapi import APIRouter, Depends, HTTPException, status

# Baskt imports
from core.deps import get_backtest_service, get_current_user
from schema.backtest_schema import BacktestRequest, BasktAssetsResponse, BacktestResponse
from services.backtest_service import BacktestService
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
    if isinstance(err, HTTPException):
        raise err

    for exception_type, status_code in BACKTEST_ERROR_STATUS_MAP:
        if isinstance(err, exception_type):
            raise HTTPException(status_code=status_code, detail=str(err)) from err

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Unexpected backtest error: {err}",
    ) from err


@router.get("/tradeable-fractionable-us-baskt-assets", response_model=BasktAssetsResponse)
def get_tradeable_fractionable_us_baskt_assets(
    backtest_service: BacktestService = Depends(get_backtest_service),
    user: Dict[str, Any] = Depends(get_current_user)
) -> BasktAssetsResponse:
    try:
        baskt_assets = backtest_service.get_tradeable_fractionable_US_baskt_assets()
        return BasktAssetsResponse(baskt_assets=baskt_assets)
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
            - weight (float): portfolio weight fraction (0..1)
            - direction (int): +1 for long, -1 for short
            - leverage (float/int, optional): leverage multiplier; defaults to 1 if omitted
        user: Authenticated user from dependency injection; used for access control.
        svc: BacktestService dependency that performs the backtest computation.

    Returns:
        Dict[str, Any]:
            {
                "dates": list[str],                 # ISO date strings aligned with output series
                "cumulative_returns": list[float],  # portfolio cumulative return values by date
                "metrics": dict[str, float | None]  # summary metrics (e.g., cagr, volatility, tilt)
            }
    """
    try:
        positions_conf = json.loads(positions)
        if not isinstance(positions_conf, list):
            raise ValueError("positions must be a JSON list")

        result = svc.run_backtest(
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            positions_conf=positions_conf
        )
        return BacktestResponse(**result)

    except Exception as e:
        _raise_backtest_http_exception(e)
