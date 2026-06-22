"""Response schemas for stock analytics routes."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, RootModel


class StockAnalyticsPeriodResponse(BaseModel):
    """Performance series and metrics for one stock analytics period."""

    timeframe: str
    timestamp: List[str]
    cumulative_returns: List[float]
    cagr: Optional[float] = None
    annualized_volatility: Optional[float] = None
    leverage_adjusted_direction: Optional[float] = None


class StockAnalyticsResponse(RootModel[Dict[str, StockAnalyticsPeriodResponse]]):
    """Stock analytics keyed by period label."""

