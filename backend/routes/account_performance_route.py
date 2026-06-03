from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.deps import get_account_performance_service, get_current_user
from services.account_performance_service import AccountPerformanceService


router = APIRouter(prefix="/account-performance", tags=["account-performance"])




@router.get("/account-id")
def get_account_performance(
	user=Depends(get_current_user),
	service: AccountPerformanceService = Depends(get_account_performance_service),
):
	cognito_user_id = user["sub"]
	try:
		return service.get_account_equity_graph(cognito_user_id=cognito_user_id)
	except Exception as e:
		print(e)
		
