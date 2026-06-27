# backend/schema/investment_analytics_schema.py

# Python imports
from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import datetime


class EquityGraphResponse(BaseModel):
    equity: List[float]
    timestamp: List[datetime]


class AccountAnalyticsResponse(BaseModel):
    cash: float
    equity: float
    equity_graph: Dict[str, EquityGraphResponse]
    portfolio_allocations: Dict[str, Dict[str, float | str]]