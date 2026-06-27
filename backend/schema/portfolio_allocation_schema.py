# backend/schema/portfolio_allocation_schema.py

# Python imports
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class PortfolioAllocationTransactionResponse(BaseModel):
    transaction_id: str
    created_at: datetime
    filled_at: datetime
    requested_amount: Optional[float] # if None, it is withdraw all or update
    number_orders: int
    transaction_type: str # DEPOSIT | UPDATE | WITHDRAW | WITHDRAW_ALL
    cost_basis: float
    order_fill_percent: float
    status: str # QUEUED | PARTIALLY_FILLED | FULLY_FILLED | CANCELLED


class PortfolioAllocationResponse(BaseModel):
    portfolio_id: str
    transaction_history: Optional[List[PortfolioAllocationTransactionResponse]] = None
    total_cost_basis: Optional[float] = None
    equity: Optional[float] = None
    profit_loss: Optional[float] = None
    profit_loss_percent: Optional[float] = None
