from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from starlette import status

from core.deps import get_account_performance_service, get_current_user, get_current_active_alpaca_account
from schema.account_performance_schema import PortfolioAllocationPerformanceResponse
from services.account_performance_service import AccountPerformanceService


router = APIRouter(prefix="/account-performance", tags=["account-performance"])


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


@router.get(
	"/portfolio-allocation/{portfolio_id}",
	response_model=PortfolioAllocationPerformanceResponse,
)
def get_portfolio_allocation_performance(
	portfolio_id: str,
	user=Depends(get_current_user),
	active_alpaca_account=Depends(get_current_active_alpaca_account),
	service: AccountPerformanceService = Depends(get_account_performance_service),
):
	try:
		performance = service.get_portfolio_allocation_performance(
			cognito_user_id=user["sub"],
			portfolio_id=portfolio_id,
		)
		if performance is None:
			raise HTTPException(
				status_code=status.HTTP_404_NOT_FOUND,
				detail="Portfolio allocation not found.",
			)
		return performance
	except HTTPException:
		raise
	except Exception as e:
		raise HTTPException(
			status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
			detail=f"Unexpected portfolio allocation performance error: {e}",
		) from e



