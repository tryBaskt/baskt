# backend/routes/trade_execution_route.py

# Python imports
from __future__ import annotations
from typing import Any, Dict
from starlette.status import (
    HTTP_202_ACCEPTED,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_CONTENT,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_502_BAD_GATEWAY,
)

# Alpaca imports
from alpaca.broker.models import Account

# Fastapi imports
from fastapi import APIRouter, Depends, HTTPException

# Baskt imports
from core.deps import (
    get_current_active_alpaca_account,
    get_current_user,
    get_trade_execution_queuing_service,
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
from services.trade_execution_queuing_service import (
    TradeExecutionQueuingInternalServerError,
    TradeExecutionQueuingService,
)

router = APIRouter(prefix="/trade-execution", tags=["trade-execution"])


def _raise_trade_execution_http_exception(err: Exception) -> None:
    if isinstance(err, HTTPException):
        raise err

    if isinstance(err, TradeExecutionQueuingInternalServerError):
        if err.code == "TRADE_EXECUTION_QUEUE_LOCKED":
            status_code = HTTP_409_CONFLICT
        elif err.code in {
            "TRADE_EXECUTION_QUEUE_SEND_FAILED",
            "TRADE_EXECUTION_QUEUE_MESSAGE_SERIALIZATION_FAILED",
        }:
            status_code = HTTP_502_BAD_GATEWAY
        elif err.code in {
            "TRADE_EXECUTION_QUEUE_FIELD_REQUIRED",
            "TRADE_EXECUTION_QUEUE_AMOUNT_INVALID",
            "TRADE_EXECUTION_QUEUE_MINIMUM_BALANCE",
            "TRADE_EXECUTION_QUEUE_AMOUNT_EXCEEDS_EQUITY",
            "TRADE_EXECUTION_QUEUE_NO_POSITIONS",
            "TRADE_EXECUTION_QUEUE_STOCK_MISMATCH",
            "TRADE_EXECUTION_QUEUE_STOCK_NOT_TRADABLE",
            "TRADE_EXECUTION_QUEUE_STOCK_NOT_SHORTABLE",
        }:
            status_code = HTTP_422_UNPROCESSABLE_CONTENT
        else:
            status_code = HTTP_500_INTERNAL_SERVER_ERROR
        raise HTTPException(
            status_code=status_code,
            detail={"message": str(err), "code": err.code},
        ) from err

    raise HTTPException(
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "message": f"Unexpected trade queuing error: {err}",
            "code": "TRADE_EXECUTION_QUEUE_UNEXPECTED_ERROR",
        },
    ) from err


@router.post("/portfolios/{portfolio_id}/deposit", response_model=DepositIntoPortfolioResponse, status_code=HTTP_202_ACCEPTED)
def deposit_into_portfolio(
    portfolio_id: str,
    request: DepositIntoPortfolioRequest,
    queuing_service: TradeExecutionQueuingService = Depends(get_trade_execution_queuing_service),
    user: Dict[str, Any] = Depends(get_current_user),
    _active_alpaca_account: Account = Depends(get_current_active_alpaca_account),
) -> DepositIntoPortfolioResponse:
    try:
        cognito_user_id = user["sub"]
        alpaca_account_id = user["custom:alpaca_acct_id"]

        queuing_service.queue_portfolio_deposit(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=request.portfolio_owner_cognito_user_id,
            amount=request.amount,
            cognito_user_id=cognito_user_id,
            alpaca_account_id=alpaca_account_id
        )

        return DepositIntoPortfolioResponse(success=True)
    except Exception as e:
        _raise_trade_execution_http_exception(e)


@router.post("/portfolios/{portfolio_id}/withdrawal", response_model=WithdrawFromPortfolioResponse, status_code=HTTP_202_ACCEPTED)
def withdraw_from_portfolio(
    portfolio_id: str,
    request: WithdrawFromPortfolioRequest,
    queuing_service: TradeExecutionQueuingService = Depends(get_trade_execution_queuing_service),
    user: Dict[str, Any] = Depends(get_current_user),
    _active_alpaca_account: Any = Depends(get_current_active_alpaca_account),
) -> WithdrawFromPortfolioResponse:
    """Withdraw funds from a portfolio proportional to latest snapshot allocations."""
    try:
        cognito_user_id = user["sub"]
        alpaca_account_id = user["custom:alpaca_acct_id"]

        queuing_service.queue_portfolio_withdrawal(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=request.portfolio_owner_cognito_user_id,
            amount=request.amount,
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )

        return WithdrawFromPortfolioResponse(success=True)
    except Exception as e:
        _raise_trade_execution_http_exception(e)


@router.post("/portfolios/{portfolio_id}/withdraw-all",response_model=WithdrawAllPortfolioResponse, status_code=HTTP_202_ACCEPTED)
def sell_all_from_portfolio(
    portfolio_id: str,
    request: WithdrawAllPortfolioRequest,
    queuing_service: TradeExecutionQueuingService = Depends(get_trade_execution_queuing_service),
    user: Dict[str, Any] = Depends(get_current_user),
    _active_alpaca_account: Any = Depends(get_current_active_alpaca_account),
) -> WithdrawAllPortfolioResponse:
    try:
        cognito_user_id = user["sub"]
        alpaca_account_id = user["custom:alpaca_acct_id"]

        queuing_service.queue_portfolio_withdraw_all(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=request.portfolio_owner_cognito_user_id,
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )

        return WithdrawAllPortfolioResponse(success=True)
    except Exception as e:
        _raise_trade_execution_http_exception(e)


@router.post("/stocks/{asset_id}/buy", response_model=BuyStockResponse, status_code=HTTP_202_ACCEPTED)
def buy_stock(
    asset_id: str,
    request: BuyStockRequest,
    queuing_service: TradeExecutionQueuingService = Depends(get_trade_execution_queuing_service),
    user: Dict[str, Any] = Depends(get_current_user),
    _active_alpaca_account: Account = Depends(get_current_active_alpaca_account),
) -> BuyStockResponse:
    try:
        queuing_service.queue_stock_buy(
            symbol=request.symbol.upper(),
            asset_id=asset_id,
            amount=request.amount,
            cognito_user_id=user["sub"],
            alpaca_account_id=user["custom:alpaca_acct_id"],
        )
        return BuyStockResponse(success=True)
    except Exception as error:
        _raise_trade_execution_http_exception(error)


@router.post("/stocks/{asset_id}/sell", response_model=SellStockResponse, status_code=HTTP_202_ACCEPTED)
def sell_stock(
    asset_id: str,
    request: SellStockRequest,
    queuing_service: TradeExecutionQueuingService = Depends(get_trade_execution_queuing_service),
    user: Dict[str, Any] = Depends(get_current_user),
    _active_alpaca_account: Account = Depends(get_current_active_alpaca_account),
) -> SellStockResponse:
    try:
        queuing_service.queue_stock_sell(
            symbol=request.symbol.upper(),
            asset_id=asset_id,
            amount=request.amount,
            alpaca_account_id=user["custom:alpaca_acct_id"],
            cognito_user_id=user["sub"],
        )
        return SellStockResponse(success=True)
    except Exception as error:
        _raise_trade_execution_http_exception(error)


@router.post("/stocks/{asset_id}/close", response_model=CloseStockResponse, status_code=HTTP_202_ACCEPTED)
def close_stock(
    asset_id: str,
    request: CloseStockRequest,
    queuing_service: TradeExecutionQueuingService = Depends(get_trade_execution_queuing_service),
    user: Dict[str, Any] = Depends(get_current_user),
    _active_alpaca_account: Account = Depends(get_current_active_alpaca_account),
) -> CloseStockResponse:
    try:
        queuing_service.queue_stock_close(
            symbol=request.symbol.upper(),
            asset_id=asset_id,
            alpaca_account_id=user["custom:alpaca_acct_id"],
            cognito_user_id=user["sub"],
        )
        return CloseStockResponse(success=True)
    except Exception as error:
        _raise_trade_execution_http_exception(error)
