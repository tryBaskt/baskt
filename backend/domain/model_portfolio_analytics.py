# backend/domain/models.py

# Python imports
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

# Pandas imports
import pandas as pd

@dataclass(frozen=True)
class ModelPortfolioAnalyticsPosition:
    """
    Simplified position for model portfolios (no time series).
    """
    symbol: str
    direction: int  # +1 long, -1 short
    leverage: float
    current_weight: float

@dataclass(frozen=True)
class ModelPortfolioAnalyticsSnapshot:
    """
    A snapshot of positions at a point in time.
    """
    positions: List[ModelPortfolioAnalyticsPosition]
    timestamp: datetime

