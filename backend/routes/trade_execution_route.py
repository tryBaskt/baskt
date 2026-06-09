# backend/routes/trade_execution_route.py

# Python imports
from __future__ import annotations
from typing import Any, Dict, List
import logging
from starlette import status

# Fastapi imports
from fastapi import APIRouter, Depends, HTTPException

# Baskt imports
from core.deps import (
    get_current_active_alpaca_account,
    get_current_user,
    get_trade_execution_service,
)
from schema.trade_execution_schema import (
    DepositIntoPortfolioRequest,
    DepositIntoPortfolioResponse,
    PortfolioInvestmentValueResponse,
    RefreshFilledOrdersRequest,
    RefreshFilledOrdersResponse,
    SellAllPortfolioRequest,
    SellAllPortfolioResponse,
    WithdrawFromPortfolioRequest,
    WithdrawFromPortfolioResponse,
)
from services.trade_execution_service import TradeExecutionService

router = APIRouter(prefix="/trade-execution", tags=["trade-execution"])
logger = logging.getLogger("uvicorn.error")


def _raise_trade_execution_http_exception(err: Exception) -> None:
    if isinstance(err, HTTPException):
        raise err

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Unexpected trade execution error: {err}",
    ) from err


def _extract_order_ids(orders: List[Any]) -> List[str]:
    order_ids: List[str] = []
    for order in orders:
        order_id = getattr(order, "id", None)
        if order_id is None and isinstance(order, dict):
            order_id = order.get("id") or order.get("order_id")
        if order_id is not None:
            order_ids.append(str(order_id))
    return order_ids


@router.post(
    "/portfolios/{portfolio_id}/deposits",
    response_model=DepositIntoPortfolioResponse,
)
def deposit_into_portfolio(
    portfolio_id: str,
    request: DepositIntoPortfolioRequest,
    trade_execution_service: TradeExecutionService = Depends(get_trade_execution_service),
    user: Dict[str, Any] = Depends(get_current_user),
    _active_alpaca_account: Any = Depends(get_current_active_alpaca_account),
) -> DepositIntoPortfolioResponse:
    try:
        cognito_user_id = user["sub"]

        orders = trade_execution_service.execute_deposit_to_portfolio(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=request.portfolio_owner_cognito_user_id,
            deposit_amount=request.amount,
            cognito_user_id=cognito_user_id,
        )
        order_ids = _extract_order_ids(orders)

        logger.info(f"Deposit created orders: {order_ids}")
        return DepositIntoPortfolioResponse(success=True, order_ids=order_ids)
    except Exception as e:
        _raise_trade_execution_http_exception(e)



@router.post(
    "/portfolios/{portfolio_id}/withdrawals",
    response_model=WithdrawFromPortfolioResponse,
)
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

        orders = trade_execution_service.execute_withdraw_from_portfolio(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=request.portfolio_owner_cognito_user_id,
            withdraw_amount=request.amount,
            cognito_user_id=cognito_user_id,
        )
        order_ids = _extract_order_ids(orders)

        logger.info(f"Withdraw created orders: {order_ids}")
        return WithdrawFromPortfolioResponse(success=True, order_ids=order_ids)
    except Exception as e:
        _raise_trade_execution_http_exception(e)


@router.post(
    "/portfolios/{portfolio_id}/sell-all",
    response_model=SellAllPortfolioResponse,
)
def sell_all_from_portfolio(
    portfolio_id: str,
    request: SellAllPortfolioRequest,
    trade_execution_service: TradeExecutionService = Depends(get_trade_execution_service),
    user: Dict[str, Any] = Depends(get_current_user),
    _active_alpaca_account: Any = Depends(get_current_active_alpaca_account),
) -> SellAllPortfolioResponse:
    try:
        cognito_user_id = user["sub"]

        orders = trade_execution_service.execute_withdraw_all_from_portfolio(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=request.portfolio_owner_cognito_user_id,
            cognito_user_id=cognito_user_id,
        )
        order_ids = _extract_order_ids(orders)

        logger.info(f"Sell all created orders: {order_ids}")
        return SellAllPortfolioResponse(success=True, order_ids=order_ids)
    except Exception as e:
        _raise_trade_execution_http_exception(e)


@router.get(
    "/portfolios/{portfolio_id}/investment",
    response_model=PortfolioInvestmentValueResponse,
)
def get_portfolio_investment_value(
    portfolio_id: str,
    trade_execution_service: TradeExecutionService = Depends(get_trade_execution_service),
    user: Dict[str, Any] = Depends(get_current_user),
    _active_alpaca_account: Any = Depends(get_current_active_alpaca_account),
) -> PortfolioInvestmentValueResponse:
    try:
        invested_amount = trade_execution_service.get_portfolio_invested_amount(
            cognito_user_id=user["sub"],
            portfolio_id=portfolio_id,
        )
        return PortfolioInvestmentValueResponse(invested_amount=invested_amount)
    except Exception as e:
        _raise_trade_execution_http_exception(e)


@router.post(
    "/orders/refresh",
    response_model=RefreshFilledOrdersResponse,
)
def refresh_orders(
    request: RefreshFilledOrdersRequest,
    trade_execution_service: TradeExecutionService = Depends(get_trade_execution_service),
    user: Dict[str, Any] = Depends(get_current_user),
    _active_alpaca_account: Any = Depends(get_current_active_alpaca_account),
) -> RefreshFilledOrdersResponse:
    cognito_user_id = user["sub"]
    try:
        newly_filled_order_count = trade_execution_service.realize_filled_orders(
            cognito_user_id=cognito_user_id,
            alpaca_account_id=user["custom:alpaca_acct_id"],
            portfolio_owner_cognito_user_id=request.portfolio_owner_cognito_user_id,
            portfolio_id=request.portfolio_id,
        )
        return RefreshFilledOrdersResponse(
            success=True,
            newly_filled_order_count=newly_filled_order_count,
        )
    except Exception as e:
        _raise_trade_execution_http_exception(e)
