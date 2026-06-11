# backend/routes/account_performance_route.py

# Python imports
from __future__ import annotations
from typing import Dict, Any
from starlette.status import HTTP_200_OK, HTTP_201_CREATED, HTTP_403_FORBIDDEN, HTTP_422_UNPROCESSABLE_CONTENT, HTTP_500_INTERNAL_SERVER_ERROR

# Fastapi imports
from fastapi import APIRouter, Depends, HTTPException

# Baskt imports
from core.deps import get_account_performance_service, get_current_user, get_current_active_alpaca_account
from schema.account_performance_schema import (
	PortfolioAllocationTransactionResponse,
	PortfolioAllocationListTransactionResponse
)
from services.account_performance_service import AccountPerformanceService

# Alpaca imports
from alpaca.broker.models import Account

router = APIRouter(prefix="/account-performance", tags=["account-performance"])

def _raise_trade_execution_http_exception(err: Exception) -> None:
    pass


@router.get("/account-id")
def get_account_performance(
	user=Depends(get_current_user),
	active_alpaca_account = Depends(get_current_active_alpaca_account),
	service: AccountPerformanceService = Depends(get_account_performance_service),
):
	alpaca_account_id = user["custom:alpaca_acct_id"]
	try:
		return service.get_account_performance(alpaca_account_id=alpaca_account_id)
	except Exception as e:
		print(e)

@router.get("/portfolio-id/transactions", response_model=PortfolioAllocationListTransactionResponse, status_code=HTTP_200_OK)
def get_portfolio_allocation_transactions(
	portfolio_id: str,
	user: Dict[str, Any]=Depends(get_current_user),
	active_alpaca_account: Account = Depends(get_current_active_alpaca_account),
	service: AccountPerformanceService = Depends(get_account_performance_service),
):
	
	cognito_user_id = user["sub"]

	try:
		transactions = service.get_portfolio_allocation_transactions(cognito_user_id=cognito_user_id,portfolio_id=portfolio_id)
		list_transaction = [
			PortfolioAllocationTransactionResponse(
				transaction_id=transaction["transaction_id"],
				transaction_amount=transaction["transaction_amount"],
				transaction_date=transaction["transaction_date"],
				transaction_type=transaction["transaction_type"],
				transaction_filled_percent=transaction["transaction_filled_percent"]
			)
			for transaction in transactions
		]
	except Exception as e:
		_raise_trade_execution_http_exception(err=e)

	return PortfolioAllocationListTransactionResponse(
		list_transaction=list_transaction
	)

# @router.get(
# 	"/portfolio-allocation/{portfolio_id}",
# 	response_model=PortfolioAllocationPerformanceResponse,
# )
# def get_portfolio_allocation_performance(
# 	portfolio_id: str,
# 	user=Depends(get_current_user),
# 	active_alpaca_account=Depends(get_current_active_alpaca_account),
# 	service: AccountPerformanceService = Depends(get_account_performance_service),
# ):
# 	try:
# 		performance = service.get_portfolio_allocation_performance(
# 			cognito_user_id=user["sub"],
# 			portfolio_id=portfolio_id,
# 		)
# 		if performance is None:
# 			raise HTTPException(
# 				status_code=status.HTTP_404_NOT_FOUND,
# 				detail="Portfolio allocation not found.",
# 			)
# 		return performance
# 	except HTTPException:
# 		raise
# 	except Exception as e:
# 		raise HTTPException(
# 			status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
# 			detail=f"Unexpected portfolio allocation performance error: {e}",
# 		) from e



