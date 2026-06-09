# Python imports
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
from typing import Optional

@dataclass(frozen=True)
class BacktestMetrics:
    final_cumulative_return: Optional[float]
    cagr: Optional[float]
    leverage_adjusted_direction: Optional[float]
    annualized_volatility: Optional[float]

@dataclass(frozen=True)
class BacktestPosition:
    """
    Domain representation of a single portfolio position.
    time_series is the historical OHLCV dataframe indexed by datetime.
    """
    symbol: str
    time_series: pd.DataFrame
    weight: float
    direction: int   # +1 long, -1 short
    leverage: float = 1