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

router = APIRouter()
logger = logging.getLogger("uvicorn.error")


@router.post("/deposit-portfolio/{portfolio_id}")
def deposit_into_portfolio(
    portfolio_id: str,
    request: Dict[str, Any],
    trade_execution_service: TradeExecutionService = Depends(get_trade_execution_service),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    

    try:
        amount_raw = request.get("amount")
        if amount_raw is None:
            raise HTTPException(status_code=400, detail="Missing 'amount' in request body")
        try:
            amount = float(amount_raw)
        except Exception:
            raise HTTPException(status_code=400, detail="'amount' must be a number")
        if amount <= 0:
            raise HTTPException(status_code=400, detail="'amount' must be > 0")

        user_id = user["sub"]
        portfolio_owner_id = request.get("portfolio_owner_id")

        order_ids = trade_execution_service.execute_deposit_to_portfolio(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            deposit_amount=amount,
            user_id=user_id,
        )

        logger.info(f"Deposit created orders: {order_ids}")
        return {"success": True, "order_ids": order_ids}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail = f"Unexpected trade execution error: {str(e)}")



@router.post("/withdraw-portfolio/{portfolio_id}")
def withdraw_from_portfolio(
    portfolio_id: str,
    request: Dict[str, Any],
    trade_execution_service: TradeExecutionService = Depends(get_trade_execution_service),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Withdraw funds from a portfolio proportional to latest snapshot allocations."""
    try:
        amount_raw = request.get("amount")
        if amount_raw is None:
            raise HTTPException(status_code=400, detail="Missing 'amount' in request body")
        try:
            amount = float(amount_raw)
        except Exception:
            raise HTTPException(status_code=400, detail="'amount' must be a number")
        if amount <= 0:
            raise HTTPException(status_code=400, detail="'amount' must be > 0")

        user_id = user["sub"]
        portfolio_owner_id = request.get("portfolio_owner_id")

        order_ids = trade_execution_service.execute_withdraw_from_portfolio(
            portfolio_id=portfolio_id,
            portfolio_owner_id=portfolio_owner_id,
            withdraw_amount=amount,
            user_id=user_id,
        )

        logger.info(f"Withdraw created orders: {order_ids}")
        return {"success": True, "order_ids": order_ids}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail = f"Unexpected trade execution error: {str(e)}")
    


@router.get("/refresh-orders")
def refresh_orders(
    request: Dict[str, Any],
    trade_execution_service: TradeExecutionService = Depends(get_trade_execution_service),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    user_id = user["sub"]
    try:
        portfolio_owner_id = request.get("portfolio_owner_id")
        portfolio_id = request.get("portfolio_id")

        if not portfolio_owner_id:
            raise HTTPException(status_code=400, detail="Missing 'portfolio_owner_id' in request body")
        if not portfolio_id:
            raise HTTPException(status_code=400, detail="Missing 'portfolio_id' in request body")

        statuses = trade_execution_service.realize_filled_orders(
            user_id=user_id,
            portfolio_owner_id=str(portfolio_owner_id),
            portfolio_id=str(portfolio_id),
        )
        # Already normalized in service
        return {"orders": statuses or []}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail = f"Unexpected trade execution error: {str(e)}")

