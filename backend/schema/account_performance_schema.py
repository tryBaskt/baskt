# backend/schema/account_performance_schema.py

# Python imports
from pydantic import BaseModel
from typing import List

class EquityGraphRequest(BaseModel):
    alpaca_account_id: str
    cognito_username: str


class PortfolioAllocationPerformanceResponse(BaseModel):
    current_value: float
    allocation_amount: float
    profit_loss: float
    profit_loss_pct: float

class PortfolioAllocationTransactionResponse(BaseModel):
    transaction_id: str
    transaction_amount: float
    transaction_date: str
    transaction_type: str
    transaction_filled_percent: float

class PortfolioAllocationListTransactionResponse(BaseModel):
    list_transaction: List[PortfolioAllocationTransactionResponse]