"""Domain models for allocations and their transaction history."""

# Python imports
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class BaseAllocationTransactionSnapshot:
    transaction_id: str
    created_at: datetime
    updated_at: datetime
    requested_amount: Optional[float]
    transaction_type: str # PORTFOLIO: DEPOSIT, WITHDRAW, OR WITHDRAW_ALL || STOCK: BUY, SELL, CLOSE
    status: str # QUEUED | ORDERED | PROCESSING | PARTIALLY_FILLED | FULLY_FILLED | FAILED 
    filled_at: Optional[datetime] = None
    cost_basis: Optional[float] = None
    status_explanation: Optional[str] = None


@dataclass
class PortfolioAllocationTransactionSnapshot(BaseAllocationTransactionSnapshot):
    portfolio_snapshot_id: Optional[str] = None
    number_orders: Optional[int] = None
    order_fill_percent: Optional[float] = None


@dataclass
class StockAllocationTransactionSnapshot(BaseAllocationTransactionSnapshot):
    number_orders: Optional[int] = None
    order_fill_percent: Optional[float] = None


@dataclass
class BaseAllocationPosition:
    symbol: str
    filled_quantity: float
    direction: int
    filled_avg_price: float


@dataclass
class PortfolioAllocationPosition(BaseAllocationPosition):
    pass


@dataclass
class StockAllocationPosition(BaseAllocationPosition):
    pass


@dataclass
class PortfolioAllocationPositionSnapshot:
    positions: List[PortfolioAllocationPosition]
    timestamp: datetime


@dataclass
class StockAllocationPositionSnapshot:
    position: Optional[StockAllocationPosition]
    timestamp: datetime


@dataclass
class BaseAllocation:
    allocation_id: str
    cognito_user_id: str
    total_cost_basis: float
    open_positions: bool 
    open_orders: bool 
    allocation_type: str # MODEL_PORTFOLIO | STOCK


@dataclass
class PortfolioAllocation(BaseAllocation):
    position_history: List[PortfolioAllocationPositionSnapshot]
    transaction_history: List[PortfolioAllocationTransactionSnapshot]
    portfolio_name: str


@dataclass
class StockAllocation(BaseAllocation):
    position_history: List[StockAllocationPositionSnapshot]
    transaction_history: List[StockAllocationTransactionSnapshot]
    symbol: str
