# backend/schema/backtest_schema.py


# Python imports
from __future__ import annotations
from pydantic import BaseModel, Field
from datetime import date
from typing import List, Optional


class BacktestPositionRequest(BaseModel):
    symbol: str
    weight: Optional[float] = Field(default=None, ge=0, le=1)
    target_weight: Optional[float] = Field(default=None, ge=0, le=1)
    direction: int
    leverage: float = 1.0


class BacktestRequest(BaseModel):
    start_date: date
    end_date: date
    positions: List[BacktestPositionRequest]


class BacktestAnalyticsResponse(BaseModel):
    start_date: date
    end_date: date
    cumulative_returns: List[float]
    final_cumulative_return: Optional[float]
    cagr: Optional[float]
    leverage_adjusted_direction: Optional[float]
    annualized_volatility: Optional[float]




