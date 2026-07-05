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
    snapshot_id: str


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


@dataclass(frozen=True)
class ModelPortfolioOpenSearchResult:
    """Searchable model portfolio metadata returned to callers."""

    portfolio_id: str
    portfolio_name: str
    description: str | None
    portfolio_owner_cognito_user_id: str
    portfolio_owner_display_name: str | None
    created_at: str
    updated_at: str
    visibility: str
    score: float | None


@dataclass(frozen=True)
class ModelPortfoliosOpenSearchResult:
    """Paginated model portfolio search response."""
    model_portfolios: List[ModelPortfolioOpenSearchResult]
    total: int
    limit: int
    offset: int
