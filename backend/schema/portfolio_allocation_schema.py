# backend/schema/portfolio_allocation_schema.py

# Python imports
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class PortfolioAllocationTransactionResponse(BaseModel):
    transaction_id: str
    model_portfolio_snapshot_id: Optional[str] = None
    created_at: datetime
    filled_at: Optional[datetime] = None
    updated_at: datetime
    requested_amount: Optional[float]  # None for withdraw-all or update
    number_orders: Optional[int] = None
    transaction_type: str  # DEPOSIT | UPDATE | WITHDRAW | WITHDRAW_ALL
    cost_basis: Optional[float] = None
    order_fill_percent: Optional[float] = None
    status: str  # QUEUED | PROCESSING | ORDERED | PARTIALLY_FILLED | FULLY_FILLED | CANCELLED | FAILED
    status_explanation: Optional[str] = None


class PortfolioAllocationResponse(BaseModel):
    portfolio_id: str
    transaction_history: Optional[List[PortfolioAllocationTransactionResponse]] = None
    total_cost_basis: Optional[float] = None
    equity: Optional[float] = None
    profit_loss: Optional[float] = None
    profit_loss_percent: Optional[float] = None
