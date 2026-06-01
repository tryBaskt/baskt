# backend/routes/portfolio_allocation_route.py

# Python imports
from __future__ import annotations
from typing import Dict, Any
import logging
from starlette import status

# Fastapi imports
from fastapi import APIRouter, Depends, HTTPException

# Baskt imports
from core.deps import get_current_user, get_trade_execution_service
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


def _get_positive_amount(request: Dict[str, Any]) -> float:
    amount_raw = request.get("amount")
    if amount_raw is None:
        raise HTTPException(status_code=400, detail="Missing 'amount' in request body")

    try:
        amount = float(amount_raw)
    except Exception as err:
        raise HTTPException(status_code=400, detail="'amount' must be a number") from err

    if amount <= 0:
        raise HTTPException(status_code=400, detail="'amount' must be > 0")

    return amount


@router.post("/portfolios/{portfolio_id}/deposits")
def deposit_into_portfolio(
    portfolio_id: str,
    request: Dict[str, Any],
    trade_execution_service: TradeExecutionService = Depends(get_trade_execution_service),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        amount = _get_positive_amount(request)
        cognito_user_id = user["sub"]
        portfolio_owner_cognito_user_id = request.get("portfolio_owner_cognito_user_id")

        order_ids = trade_execution_service.execute_deposit_to_portfolio(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
            deposit_amount=amount,
            cognito_user_id=cognito_user_id,
        )

        logger.info(f"Deposit created orders: {order_ids}")
        return {"success": True, "order_ids": order_ids}
    except Exception as e:
        _raise_trade_execution_http_exception(e)



@router.post("/portfolios/{portfolio_id}/withdrawals")
def withdraw_from_portfolio(
    portfolio_id: str,
    request: Dict[str, Any],
    trade_execution_service: TradeExecutionService = Depends(get_trade_execution_service),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Withdraw funds from a portfolio proportional to latest snapshot allocations."""
    try:
        amount = _get_positive_amount(request)
        cognito_user_id = user["sub"]
        portfolio_owner_cognito_user_id = request.get("portfolio_owner_cognito_user_id")

        order_ids = trade_execution_service.execute_withdraw_from_portfolio(
            portfolio_id=portfolio_id,
            portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
            withdraw_amount=amount,
            cognito_user_id=cognito_user_id,
        )

        logger.info(f"Withdraw created orders: {order_ids}")
        return {"success": True, "order_ids": order_ids}
    except Exception as e:
        _raise_trade_execution_http_exception(e)
    


@router.post("/orders/refresh")
def refresh_orders(
    request: Dict[str, Any],
    trade_execution_service: TradeExecutionService = Depends(get_trade_execution_service),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    cognito_user_id = user["sub"]
    try:
        portfolio_owner_cognito_user_id = request.get("portfolio_owner_cognito_user_id")
        portfolio_id = request.get("portfolio_id")

        if not portfolio_owner_cognito_user_id:
            raise HTTPException(status_code=400, detail="Missing 'portfolio_owner_cognito_user_id' in request body")
        if not portfolio_id:
            raise HTTPException(status_code=400, detail="Missing 'portfolio_id' in request body")

        statuses = trade_execution_service.realize_filled_orders(
            cognito_user_id=cognito_user_id,
            portfolio_owner_cognito_user_id=str(portfolio_owner_cognito_user_id),
            portfolio_id=str(portfolio_id),
        )
        # Already normalized in service
        return {"orders": statuses or []}
    except Exception as e:
        _raise_trade_execution_http_exception(e)
