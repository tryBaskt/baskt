from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class _PortfolioTradeRequest(BaseModel):
    portfolio_id: str
    portfolio_owner_cognito_user_id: str
    amount: float = Field(gt=0)


class _PortfolioTradeResponse(BaseModel):
    success: bool

class DepositIntoPortfolioRequest(_PortfolioTradeRequest):
    pass

class WithdrawFromPortfolioRequest(_PortfolioTradeRequest):
    pass

class DepositIntoPortfolioResponse(_PortfolioTradeResponse):
    pass

class WithdrawFromPortfolioResponse(_PortfolioTradeResponse):
    pass

class SellAllPortfolioRequest(_PortfolioTradeRequest):
    pass

class SellAllPortfolioResponse(_PortfolioTradeResponse):
    pass


class RefreshFilledOrdersRequest(BaseModel):
    cognito_user_id: str
    portfolio_id: str


class RefreshFilledOrdersResponse(BaseModel):
    newly_filled_order_count: int
