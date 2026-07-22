"""Domain models for portfolio allocations and their transaction history."""

# Python imports
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class PortfolioAllocationTransactionSnapshot:
    transaction_id: str
    created_at: datetime
    updated_at: datetime
    requested_amount: Optional[float]
    transaction_type: str
    status: str # QUEUED | ORDERED | PROCESSING | PARTIALLY_FILLED | FULLY_FILLED | FAILED 
    model_portfolio_snapshot_id: Optional[str] = None # only for model portfolios and when transaction is DEPOSIT or UPDATE
    filled_at: Optional[datetime] = None
    number_orders: Optional[int] = None
    cost_basis: Optional[float] = None
    order_fill_percent: Optional[float] = None
    status_explanation: Optional[str] = None


@dataclass
class PortfolioAllocationPosition:
    symbol: str
    filled_quantity: float
    direction: int
    filled_avg_price: float


@dataclass
class PortfolioAllocationPositionSnapshot:
    positions: List[PortfolioAllocationPosition]
    timestamp: datetime


@dataclass
class PortfolioAllocation:
    portfolio_id: str
    cognito_user_id: str
    position_history: List[PortfolioAllocationPositionSnapshot]
    transaction_history: List[PortfolioAllocationTransactionSnapshot]
    total_cost_basis: float
    portfolio_allocation_type: str
    portfolio_name: str


