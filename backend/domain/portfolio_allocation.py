# backend/domain/user_models.py

# Python imports
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import List

@dataclass(frozen=True)
class PortfolioAllocationPosition:
    symbol: str
    filled_quantity: float
    direction: int
    filled_avg_price: float


@dataclass(frozen=True)
class PortfolioAllocationSnapshot:
    positions: List[PortfolioAllocationPosition]
    timestamp: datetime
    allocation_amount: float
    transaction_id: str



@dataclass(frozen=True)
class PortfolioAllocation:
    portfolio_id: str
    portfolio_allocation_history: List[PortfolioAllocationSnapshot]
    cognito_user_id: str






