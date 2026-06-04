from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.deps import get_account_performance_service, get_current_user, get_current_active_alpaca_account
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
		
