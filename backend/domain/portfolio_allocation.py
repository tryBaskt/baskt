# backend/domain/user_models.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List

###########################
# USER LEVEl
###########################
@dataclass(frozen=True)
class PortfolioAllocationPosition:
    symbol: str
    filled_quantity: float
    direction: int
    filled_avg_price: float = None


@dataclass(frozen=True)
class PortfolioAllocationSnapshot:
    positions: List[PortfolioAllocationPosition] | None
    timestamp: datetime | None
    allocation_amount: float | None
    transaction_id: str



@dataclass(frozen=True)
class PortfolioAllocation:
    portfolio_id: str
    portfolio_allocation_history: List[PortfolioAllocationSnapshot]
    cognito_user_id: str






