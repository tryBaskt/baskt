# backend/routes/account_analytics_route.py

# Python imports
from __future__ import annotations
from typing import Dict, Any, List
from starlette.status import HTTP_200_OK, HTTP_500_INTERNAL_SERVER_ERROR

# Fastapi imports
from fastapi import APIRouter, Depends, HTTPException

# Alpaca imports
from alpaca.broker.models import Account

# Baskt imports
from core.deps import (
	get_account_analytics_service, 
	get_current_user, 
	get_current_active_alpaca_account, 
	get_trade_execution_service,
	get_portfolio_allocation_repository
)
from schema.account_analytics_schema import (
	PortfolioAllocationTransactionResponse,
	PortfolioAllocationAnalyticsResponse,
	AccountAnalyticsResponse,
	EquityGraphResponse
)
from services.account_analytics_service import AccountAnalyticsService, AccountAnalyticsServiceError
from services.trade_execution_service import TradeExecutionService
from repository.portfolio_allocation_repository import PortfolioAllocationRepository
from domain.portfolio_allocation import PortfolioAllocationTransactionSnapshot

# Alpaca imports
from alpaca.broker.models import Account



router = APIRouter(prefix="/account-analytics", tags=["account-performance"])


def _raise_trade_execution_http_exception(err: Exception) -> None:
    if isinstance(err, HTTPException):
        raise err

    raise HTTPException(
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Unexpected account analytics error: {err}",
    ) from err

@router.get("", response_model= AccountAnalyticsResponse, status_code=HTTP_200_OK)
def account_analytics(
	user: Dict[str, Any] = Depends(get_current_user),
	active_alpaca_account: Account = Depends(get_current_active_alpaca_account),
	service: AccountAnalyticsService = Depends(get_account_analytics_service)
) -> AccountAnalyticsResponse:
	
	cognito_user_id = user["sub"]
	alpaca_account_id = user["custom:alpaca_acct_id"]

	try:
		account_analytics_dict = service.get_account_analytics(cognito_user_id=cognito_user_id, alpaca_account_id=alpaca_account_id)

		equity_graph_response = {}
		for period in account_analytics_dict["equity_graph"]:
			period_equity_graph = account_analytics_dict["equity_graph"][period]
			equity_graph_response[period] = EquityGraphResponse(equity=period_equity_graph["equity"], timestamp=period_equity_graph["timestamp"])

		return AccountAnalyticsResponse(
			cash = account_analytics_dict["cash"],
			equity=account_analytics_dict["equity"],
			equity_graph=equity_graph_response
		)
	except Exception as err:
		_raise_trade_execution_http_exception(err=err)
	


@router.get("/portfolios/{portfolio_id}/analytics", response_model=PortfolioAllocationAnalyticsResponse, status_code=HTTP_200_OK)
def get_portfolio_allocation_analytics(
	portfolio_id: str,
	portfolio_owner_cognito_user_id: str,
	user: Dict[str, Any] = Depends(get_current_user),
	active_alpaca_account: Account = Depends(get_current_active_alpaca_account),
	service: AccountAnalyticsService = Depends(get_account_analytics_service),
	trade_execution_service: TradeExecutionService = Depends(get_trade_execution_service),
	# portfolio_allocation_repository: PortfolioAllocationRepository = Depends(get_portfolio_allocation_repository)
) -> PortfolioAllocationAnalyticsResponse:
	
	cognito_user_id = user["sub"]
	alpaca_account_id = user["custom:alpaca_acct_id"]

	try:
		trade_execution_service.realize_filled_orders(
			cognito_user_id=cognito_user_id,
			alpaca_account_id=alpaca_account_id,
			portfolio_id=portfolio_id,
			portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id
		)

		analytics_dict = service.get_portfolio_allocation_analytics(cognito_user_id=cognito_user_id,portfolio_id=portfolio_id)
		if not analytics_dict:
			return PortfolioAllocationAnalyticsResponse()
		

		transaction_history: List[PortfolioAllocationTransactionSnapshot] = analytics_dict["transaction_history"]
		list_transaction = [
			PortfolioAllocationTransactionResponse(
				transaction_id=transaction.transaction_id,
				created_at=transaction.created_at.isoformat(),
				filled_at=transaction.filled_at.isoformat(),
				requested_amount=transaction.requested_amount,
				number_orders=transaction.number_orders,
				transaction_type=transaction.transaction_type,
				filled_amount=transaction.filled_amount,
				order_fill_percent=transaction.order_fill_percent,
				status=transaction.status
			)
			for transaction in transaction_history
		]

		return PortfolioAllocationAnalyticsResponse(
			list_transaction=list_transaction,
			total_filled_amount=analytics_dict["total_filled_amount"],
			equity=analytics_dict["equity"],
			profit_loss=analytics_dict["profit_loss"],
			profit_loss_pct=analytics_dict["profit_loss_pct"]
		)
	
	except Exception as e:
		_raise_trade_execution_http_exception(err=e)


@router.get("/stocks/{asset_id}/analytics", response_model=PortfolioAllocationAnalyticsResponse, status_code=HTTP_200_OK)
def get_stock_allocation_analytics(
	asset_id: str,
	user: Dict[str, Any] = Depends(get_current_user),
	_active_alpaca_account: Account = Depends(get_current_active_alpaca_account),
	service: AccountAnalyticsService = Depends(get_account_analytics_service),
	trade_execution_service: TradeExecutionService = Depends(get_trade_execution_service),
) -> PortfolioAllocationAnalyticsResponse:
	"""Return allocation metrics and transaction history for one owned stock."""
	cognito_user_id = user["sub"]
	alpaca_account_id = user["custom:alpaca_acct_id"]

	try:
		trade_execution_service.realize_filled_orders(
			cognito_user_id=cognito_user_id,
			alpaca_account_id=alpaca_account_id,
			portfolio_id=asset_id,
		)
		analytics_dict = service.get_portfolio_allocation_analytics(
			cognito_user_id=cognito_user_id,
			portfolio_id=asset_id,
		)
		if not analytics_dict:
			return PortfolioAllocationAnalyticsResponse()

		return PortfolioAllocationAnalyticsResponse(
			list_transaction=[
				PortfolioAllocationTransactionResponse(
					transaction_id=transaction.transaction_id,
					created_at=transaction.created_at.isoformat(),
					filled_at=transaction.filled_at.isoformat(),
					requested_amount=transaction.requested_amount,
					number_orders=transaction.number_orders,
					transaction_type=transaction.transaction_type,
					filled_amount=transaction.filled_amount,
					order_fill_percent=transaction.order_fill_percent,
					status=transaction.status,
				)
				for transaction in analytics_dict["transaction_history"]
			],
			total_filled_amount=analytics_dict["total_filled_amount"],
			equity=analytics_dict["equity"],
			profit_loss=analytics_dict["profit_loss"],
			profit_loss_pct=analytics_dict["profit_loss_pct"],
		)
	except Exception as error:
		_raise_trade_execution_http_exception(err=error)
