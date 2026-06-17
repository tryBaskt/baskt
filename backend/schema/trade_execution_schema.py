from __future__ import annotations

from pydantic import BaseModel, Field


class _PortfolioOwnerRequest(BaseModel):
    portfolio_owner_cognito_user_id: str


class _PortfolioTradeRequest(_PortfolioOwnerRequest):
    amount: float = Field(gt=0)


class _PortfolioTradeResponse(BaseModel):
    success: bool

class DepositIntoPortfolioRequest(_PortfolioTradeRequest):
    pass

class WithdrawFromPortfolioRequest(_PortfolioTradeRequest):
    pass

class WithdrawAllPortfolioRequest(_PortfolioOwnerRequest):
    pass

class DepositIntoPortfolioResponse(_PortfolioTradeResponse):
    pass

class WithdrawFromPortfolioResponse(_PortfolioTradeResponse):
    pass

class WithdrawAllPortfolioResponse(_PortfolioTradeResponse):
    pass