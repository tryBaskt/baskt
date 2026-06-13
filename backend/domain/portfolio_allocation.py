# backend/domain/user_models.py

# Python imports
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

# @dataclass(frozen=True)
# class PortfolioAllocationPosition:
#     symbol: str
#     filled_quantity: float
#     direction: int
#     filled_avg_price: float


# @dataclass(frozen=True)
# class PortfolioAllocationSnapshot:
#     positions: List[PortfolioAllocationPosition]
#     timestamp: datetime
#     allocation_amount: float
#     transaction_id: str
#     status: str # QUEUED | PARTIALLY_FILLED | FULLY_FILLED
#     order_fill_percent: float
#     number_orders: int
#     transaction_type: str # DEPOSIT | UPDATE | WITHDRAW

@dataclass
class PortfolioAllocationTransactionSnapshot:
    transaction_id: str
    created_at: datetime
    filled_at: datetime
    requested_amount: float # if None, it is withdraw all
    number_orders: int
    transaction_type: str # DEPOSIT | UPDATE | WITHDRAW | WITHDRAW_ALL
    filled_amount: float
    order_fill_percent: float
    status: str # QUEUED | PARTIALLY_FILLED | FULLY_FILLED | CANCELLED


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
    total_filled_amount: float



