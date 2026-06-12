# backend/schema/account_analytics_schema.py

# Python imports
from pydantic import BaseModel
from typing import List, Optional, Dict

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
    transaction_amount: float
    transaction_date: str
    transaction_type: str
    transaction_filled_percent: float

class PortfolioAllocationListTransactionResponse(BaseModel):
    list_transaction: Optional[List[PortfolioAllocationTransactionResponse]] = None