from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class _PortfolioTradeRequest(BaseModel):
    portfolio_owner_cognito_user_id: str
    amount: float = Field(gt=0)


class _PortfolioTradeResponse(BaseModel):
    success: bool
    order_ids: List[str]


class DepositIntoPortfolioRequest(_PortfolioTradeRequest):
    pass


class DepositIntoPortfolioResponse(_PortfolioTradeResponse):
    pass


class WithdrawFromPortfolioRequest(_PortfolioTradeRequest):
    pass


class WithdrawFromPortfolioResponse(_PortfolioTradeResponse):
    pass


class SellAllPortfolioRequest(BaseModel):
    portfolio_owner_cognito_user_id: str


class SellAllPortfolioResponse(_PortfolioTradeResponse):
    pass


class PortfolioInvestmentValueResponse(BaseModel):
    invested_amount: float


class RefreshFilledOrdersRequest(BaseModel):
    portfolio_owner_cognito_user_id: str
    portfolio_id: str


class RefreshFilledOrdersResponse(BaseModel):
    success: bool
    newly_filled_order_count: int
