# backend/schema/allocation_analytics_schema.py

# Python imports
from pydantic import BaseModel, RootModel
from typing import List, Optional, Dict
from datetime import datetime

###############################
####### ALL ALLOCATIONS #######
###############################

class AllEquityGraphResponse(BaseModel):
    equity: List[float]
    timestamp: List[datetime]


class AllAllocationAnalyticsResponse(BaseModel):
    cash: float
    equity: float
    equity_graph: Dict[str, AllEquityGraphResponse]
    allocations: Dict[str, Dict[str, float | str]]

##################################
######## STOCK ALLOCATIONS #######
##################################

class StockAllocationTransactionResponse(BaseModel):
    transaction_id: str
    created_at: datetime
    filled_at: Optional[datetime] = None
    updated_at: datetime
    requested_amount: Optional[float]  # None for close
    number_orders: Optional[int] = None
    transaction_type: str  # BUY | SELL | CLOSE
    cost_basis: Optional[float] = None
    order_fill_percent: Optional[float] = None
    status: str  # QUEUED | PROCESSING | ORDERED | PARTIALLY_FILLED | FULLY_FILLED | CANCELLED | FAILED
    status_explanation: Optional[str] = None

class StockAllocationResponse(BaseModel):
    stock_id: str
    transaction_history: Optional[List[StockAllocationTransactionResponse]] = None
    total_cost_basis: Optional[float] = None
    equity: Optional[float] = None
    profit_loss: Optional[float] = None
    profit_loss_percent: Optional[float] = None
    direction: Optional[float] = None

class StockAnalyticsPeriodResponse(BaseModel):
    """Performance series and metrics for one stock analytics period."""
    timeframe: str
    timestamp: List[datetime]
    prices: List[float]
    final_cumulative_return: float
    cagr: Optional[float] = None
    annualized_volatility: Optional[float] = None
    leverage_adjusted_direction: Optional[float] = None
    alpha: Optional[float] = None
    beta: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    maximum_drawdown: Optional[float] = None
    maximum_drawdown_duration: Optional[float] = None


class StockAnalyticsResponse(RootModel[Dict[str,StockAnalyticsPeriodResponse]]):
    """Stock analytics keyed by period label."""
    pass


#################################
## MODEL PORTFOLIO ALLOCATIONS ##
#################################

class PortfolioAllocationTransactionResponse(BaseModel):
    transaction_id: str
    portfolio_snapshot_id: Optional[str] = None
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

