from pydantic import BaseModel

class EquityGraphRequest(BaseModel):
    alpaca_account_id: str
    cognito_username: str


class PortfolioAllocationPerformanceResponse(BaseModel):
    current_value: float
    allocation_amount: float
    profit_loss: float
    profit_loss_pct: float
