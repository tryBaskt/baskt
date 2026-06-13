# backend/schema/account_analytics_schema.py

# Python imports
from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import datetime

class EquityGraphRequest(BaseModel):
    alpaca_account_id: str
    cognito_username: str

class EquityGraphResponse(BaseModel):
    equity: List[float]
    timestamp: List[int]

class AccountAnalyticsResponse(BaseModel):
    cash: Optional[str]
    equity: Optional[str]
    equity_graph: Dict[str, EquityGraphResponse]


class PortfolioAllocationTransactionResponse(BaseModel):
    transaction_id: str
    created_at: str
    filled_at: str
    requested_amount: Optional[float] # if None, it is withdraw all
    number_orders: int
    transaction_type: str # DEPOSIT | UPDATE | WITHDRAW | WITHDRAW_ALL
    filled_amount: float
    order_fill_percent: float
    status: str # QUEUED | PARTIALLY_FILLED | FULLY_FILLED | CANCELLED


class PortfolioAllocationAnalyticsResponse(BaseModel):
    list_transaction: Optional[List[PortfolioAllocationTransactionResponse]] = None
    total_filled_amount: Optional[float] = None
    equity: Optional[float] = None
    profit_loss: Optional[float] = None
    profit_loss_pct: Optional[float] = None

