# backend/schema/backtest_schema.py

# Python imports
from __future__ import annotations
from pydantic import BaseModel
from datetime import date
from typing import List, Optional

class BacktestPositionRequest(BaseModel):
    symbol: str
    weight: Optional[float] = None
    target_weight: Optional[float] = None
    direction: int
    leverage: float = 1.0

class BacktestRequest(BaseModel):
    start_date: date
    end_date: date
    positions: List[BacktestPositionRequest]

class BasktAssetResponse(BaseModel):
    symbol: str
    tradable: bool
    fractionable: bool
    asset_class: str

class BasktAssetsResponse(BaseModel):
    baskt_assets: List[BasktAssetResponse]


class BacktestMetricsResponse(BaseModel):
    final_cumulative_return: Optional[float]
    cagr: Optional[float]
    leverage_adjusted_direction: Optional[float]
    annualized_volatility: Optional[float]


class BacktestResponse(BaseModel):
    dates: List[str]
    cumulative_returns: List[float]
    metrics: BacktestMetricsResponse
