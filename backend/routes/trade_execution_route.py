# backend/routes/trade_execution_route.py

# Python imports
from __future__ import annotations
from typing import Any, Dict
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR, HTTP_200_OK

# Alpaca imports
from alpaca.broker.models import Account

# Fastapi imports
from fastapi import APIRouter, Depends, HTTPException

# Baskt imports
from core.deps import (
    get_current_active_alpaca_account,
    get_current_user,
    get_trade_execution_service,
)
from schema.trade_execution_schema import (
    BuyStockRequest,
    BuyStockResponse,
    CloseStockRequest,
    CloseStockResponse,
    DepositIntoPortfolioRequest,
    DepositIntoPortfolioResponse,
    SellStockRequest,
    SellStockResponse,
    WithdrawAllPortfolioRequest,
    WithdrawAllPortfolioResponse,
    WithdrawFromPortfolioRequest,
    WithdrawFromPortfolioResponse,
)
from services.trade_execution_service import TradeExecutionService

router = APIRouter(prefix="/trade-execution", tags=["trade-execution"])


def _raise_trade_execution_http_exception(err: Exception) -> None:
    if isinstance(err, HTTPException):
        raise err

    raise HTTPException(
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Unexpected trade execution error: {err}",
    ) from err


@router.post("/portfolios/{portfolio_id}/deposit", response_model=DepositIntoPortfolioResponse)
def deposit_into_portfolio(
    portfolio_id: str,
    request: DepositIntoPortfolioRequest,
    trade_execution_service: TradeExecutionService = Depends(get_trade_execution_service),
    user: Dict[str, Any] = Depends(get_current_user),
    _active_alpaca_account: Account = Depends(get_current_active_alpaca_account),
) -> DepositIntoPortfolioResponse:
    try:
        cognito_user_id = user["sub"]
        alpaca_account_id = user["custom:alpaca_acct_id"]

        trade_execution_service.execute_deposit_to_portfolio(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=request.portfolio_owner_cognito_user_id,
            deposit_amount=request.amount,
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id
        )

        return DepositIntoPortfolioResponse(success=True)
    except Exception as e:
        _raise_trade_execution_http_exception(e)


@router.post("/portfolios/{portfolio_id}/withdrawal", response_model=WithdrawFromPortfolioResponse)
def withdraw_from_portfolio(
    portfolio_id: str,
    request: WithdrawFromPortfolioRequest,
    trade_execution_service: TradeExecutionService = Depends(get_trade_execution_service),
    user: Dict[str, Any] = Depends(get_current_user),
    _active_alpaca_account: Any = Depends(get_current_active_alpaca_account),
) -> WithdrawFromPortfolioResponse:
    """Withdraw funds from a portfolio proportional to latest snapshot allocations."""
    try:
        cognito_user_id = user["sub"]
        alpaca_account_id = user["custom:alpaca_acct_id"]

        trade_execution_service.execute_withdraw_from_portfolio(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=request.portfolio_owner_cognito_user_id,
            withdraw_amount=request.amount,
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )

        return WithdrawFromPortfolioResponse(success=True)
    except Exception as e:
        _raise_trade_execution_http_exception(e)


@router.post("/portfolios/{portfolio_id}/withdraw-all",response_model=WithdrawAllPortfolioResponse, status_code=HTTP_200_OK)
def sell_all_from_portfolio(
    portfolio_id: str,
    request: WithdrawAllPortfolioRequest,
    trade_execution_service: TradeExecutionService = Depends(get_trade_execution_service),
    user: Dict[str, Any] = Depends(get_current_user),
    _active_alpaca_account: Any = Depends(get_current_active_alpaca_account),
) -> WithdrawAllPortfolioResponse:
    try:
        cognito_user_id = user["sub"]
        alpaca_account_id = user["custom:alpaca_acct_id"]

        trade_execution_service.execute_withdraw_all_from_portfolio(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=request.portfolio_owner_cognito_user_id,
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )

        return WithdrawAllPortfolioResponse(success=True)
    except Exception as e:
        _raise_trade_execution_http_exception(e)


@router.post("/stocks/{asset_id}/buy", response_model=BuyStockResponse)
def buy_stock(
    asset_id: str,
    request: BuyStockRequest,
    trade_execution_service: TradeExecutionService = Depends(get_trade_execution_service),
    user: Dict[str, Any] = Depends(get_current_user),
    _active_alpaca_account: Account = Depends(get_current_active_alpaca_account),
) -> BuyStockResponse:
    try:
        trade_execution_service.execute_buy_to_stock(
            symbol=request.symbol.upper(),
            asset_id=asset_id,
            deposit_amount=request.amount,
            cognito_user_id=user["sub"],
            alpaca_account_id=user["custom:alpaca_acct_id"],
        )
        return BuyStockResponse(success=True)
    except Exception as error:
        _raise_trade_execution_http_exception(error)


@router.post("/stocks/{asset_id}/sell", response_model=SellStockResponse)
def sell_stock(
    asset_id: str,
    request: SellStockRequest,
    trade_execution_service: TradeExecutionService = Depends(get_trade_execution_service),
    user: Dict[str, Any] = Depends(get_current_user),
    _active_alpaca_account: Account = Depends(get_current_active_alpaca_account),
) -> SellStockResponse:
    try:
        trade_execution_service.execute_sell_to_stock(
            symbol=request.symbol.upper(),
            asset_id=asset_id,
            withdraw_amount=request.amount,
            alpaca_account_id=user["custom:alpaca_acct_id"],
            cognito_user_id=user["sub"],
        )
        return SellStockResponse(success=True)
    except Exception as error:
        _raise_trade_execution_http_exception(error)


@router.post("/stocks/{asset_id}/close", response_model=CloseStockResponse)
def close_stock(
    asset_id: str,
    request: CloseStockRequest,
    trade_execution_service: TradeExecutionService = Depends(get_trade_execution_service),
    user: Dict[str, Any] = Depends(get_current_user),
    _active_alpaca_account: Account = Depends(get_current_active_alpaca_account),
) -> CloseStockResponse:
    try:
        trade_execution_service.execute_close_stock(
            asset_id=asset_id,
            alpaca_account_id=user["custom:alpaca_acct_id"],
            cognito_user_id=user["sub"],
        )
        return CloseStockResponse(success=True)
    except Exception as error:
        _raise_trade_execution_http_exception(error)
