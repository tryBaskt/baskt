# backend/domain/backtest.py

# Python imports
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class BacktestMetrics:
    final_cumulative_return: Optional[float]
    cagr: Optional[float]
    leverage_adjusted_direction: Optional[float]
    annualized_volatility: Optional[float]

@dataclass(frozen=True)
class BacktestPosition:
    """Domain representation of a single backtest position."""
    symbol: str
    weight: float
    direction: int   # +1 long, -1 short
    leverage: float = 1
