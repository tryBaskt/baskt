# backend/schema/backtest_request.py

# Python imports
from __future__ import annotations
from pydantic import BaseModel
from datetime import date
from typing import List, Optional

# Baskt imports
from schema.model_portfolio_schema import ModelPortfolioPositionRequest
from domain.baskt import BasktAsset
from domain.backtest import BacktestMetrics


class BacktestRequest(BaseModel):
    start_date: date
    end_date: date
    positions: List[ModelPortfolioPositionRequest]

class BasktAssetsResponse(BaseModel):
    baskt_assets: List[BasktAsset]


class BacktestResponse(BaseModel):
    dates: List[str]
    cumulative_returns: List[float]
    metrics: BacktestMetrics
