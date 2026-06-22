# backend/domain/models.py

# Python imports
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

# Pandas imports
import pandas as pd

@dataclass(frozen=True)
class ModelPortfolioPosition:
    """
    Simplified position for model portfolios (no time series).
    """
    symbol: str
    target_weight: float
    direction: int  # +1 long, -1 short
    leverage: float
    model_filled_quantity: float 
    model_filled_avg_price: float 

@dataclass(frozen=True)
class ModelPortfolioSnapshot:
    """
    A snapshot of positions at a point in time.
    """
    positions: List[ModelPortfolioPosition]
    timestamp: datetime


@dataclass(frozen=True)
class ModelPortfolio:
    """
    A model portfolio with metadata and position history.
    """
    portfolio_id: str
    portfolio_owner_cognito_user_id: Optional[str]
    portfolio_name: str
    position_history: List[ModelPortfolioSnapshot]
    created_at: datetime
    updated_at: datetime
    description: Optional[str] = None

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

