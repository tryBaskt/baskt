from __future__ import annotations

from pydantic import BaseModel, Field


class _PortfolioTradeRequest(BaseModel):
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

class WithdrawAllPortfolioResponse(_PortfolioTradeResponse):
    pass


class BuyStockRequest(BaseModel):
    amount: float = Field(gt=0)


class SellStockRequest(BaseModel):
    amount: float = Field(gt=0)


class BuyStockResponse(_PortfolioTradeResponse):
    pass


class SellStockResponse(_PortfolioTradeResponse):
    pass


class CloseStockResponse(_PortfolioTradeResponse):
    pass
