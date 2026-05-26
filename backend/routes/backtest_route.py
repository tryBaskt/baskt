# backend/api/routes/backtest.py

# Python imports
from __future__ import annotations
from datetime import date
import json
from typing import Any, Dict

# Fastapi imports
from fastapi import APIRouter, Depends, HTTPException, status

# Baskt imports
from core.deps import get_backtest_service, get_current_user
from services.backtest_service import (BacktestService, 
                                       BacktestServiceCalculationError,
                                       BacktestServiceError,
                                       BacktestServiceDataError,
                                       BacktestServiceValidationError)
                                        


router = APIRouter(tags=["backtest"])


@router.get("/backtest")
def backtest(
    start_date: date,
    end_date: date,
    positions: str,
    user=Depends(get_current_user),
    svc: BacktestService = Depends(get_backtest_service),
) -> Dict[str, Any]:
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
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,detail=str(e))
    except BacktestServiceValidationError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,detail=str(e))
    except BacktestServiceDataError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,detail=str(e))
    except BacktestServiceCalculationError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,detail=str(e))
    except BacktestServiceError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,detail=f"Unexpected backtest error: {e}")

    return {
        "dates": result["dates"],
        "cumulative_returns": result["cumulative_returns"],
        "metrics": result["metrics"],
    }
