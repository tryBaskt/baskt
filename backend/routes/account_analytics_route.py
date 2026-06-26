# backend/routes/account_analytics_route.py

# Python imports
from __future__ import annotations
from typing import Dict, Any, List, Optional
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
from schema.stock_schema import StockResponse
from services.account_analytics_service import AccountAnalyticsService, AccountAnalyticsServiceError
from services.trade_execution_service import TradeExecutionService
from repository.portfolio_allocation_repository import PortfolioAllocationRepository
from domain.portfolio_allocation_domain import PortfolioAllocationTransactionSnapshot

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
			equity_graph=equity_graph_response,
			portfolio_allocations=account_analytics_dict.get("portfolio_allocations", {})
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
		transactions_list = service.get_portfolio_allocation_transactions(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id)
		if not analytics_dict and not transactions_list:
			return PortfolioAllocationAnalyticsResponse(
			)

		return PortfolioAllocationAnalyticsResponse(
			transactions=transactions_list,
			total_cost_basis=analytics_dict["total_cost_basis"],
			equity=analytics_dict["equity"],
			profit_loss=analytics_dict["profit_loss"],
			profit_loss_pct=analytics_dict["profit_loss_pct"]
		)
	
	except Exception as e:
		_raise_trade_execution_http_exception(err=e)


@router.get("/stocks/{asset_id}/analytics", response_model=PortfolioAllocationAnalyticsResponse, status_code=HTTP_200_OK)
def get_stock_allocation_analytics(
	asset_id: str,
	portfolio_owner_cognito_user_id: Optional[str] = None,
	user: Dict[str, Any] = Depends(get_current_user),
	active_alpaca_account: Account = Depends(get_current_active_alpaca_account),
	service: AccountAnalyticsService = Depends(get_account_analytics_service),
	trade_execution_service: TradeExecutionService = Depends(get_trade_execution_service),
) -> PortfolioAllocationAnalyticsResponse:
	
	cognito_user_id = user["sub"]
	alpaca_account_id = user["custom:alpaca_acct_id"]

	try:
		trade_execution_service.realize_filled_orders(
			cognito_user_id=cognito_user_id,
			alpaca_account_id=alpaca_account_id,
			portfolio_id=asset_id,
			portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id
		)

		stock_metadata_dict = service.get_stock_metadata(asset_id=asset_id)

		portfolio_allocation_analytics_response = PortfolioAllocationAnalyticsResponse(
			marginable=stock_metadata_dict["marginable"],
			shortable=stock_metadata_dict["shortable"],
			fractionable=stock_metadata_dict["fractionable"],
			tradable=stock_metadata_dict["tradable"]
		)

		analytics_dict = service.get_portfolio_allocation_analytics(cognito_user_id=cognito_user_id,portfolio_id=asset_id)
		transactions_list = service.get_portfolio_allocation_transactions(cognito_user_id=cognito_user_id, portfolio_id=asset_id)
		if not analytics_dict and not transactions_list:
			return portfolio_allocation_analytics_response
		
		portfolio_allocation_analytics_response.transactions = transactions_list
		portfolio_allocation_analytics_response.total_cost_basis = analytics_dict["total_cost_basis"]
		portfolio_allocation_analytics_response.equity=analytics_dict["equity"],
		portfolio_allocation_analytics_response.profit_loss=analytics_dict["profit_loss"],
		portfolio_allocation_analytics_response.profit_loss_pct=analytics_dict["profit_loss_pct"]

		return portfolio_allocation_analytics_response
	
	except Exception as e:
		_raise_trade_execution_http_exception(err=e)


@router.get("/stocks/{asset_id}/metadata", response_model=StockResponse, status_code=HTTP_200_OK)
def get_stock_metadata(
	asset_id: str,
	user: Dict[str, Any] = Depends(get_current_user),
	service: AccountAnalyticsService = Depends(get_account_analytics_service),
) -> StockResponse:
	del user

	try:
		stock_metadata_dict = service.get_stock_metadata(asset_id=asset_id)
		return StockResponse(
			symbol=stock_metadata_dict["symbol"],
			tradable=stock_metadata_dict["tradable"],
			fractionable=stock_metadata_dict["fractionable"],
			shortable=stock_metadata_dict["shortable"],
			marginable=stock_metadata_dict["marginable"],
			stock_id=stock_metadata_dict["stock_id"],
			stock_class=stock_metadata_dict["stock_class"],
		)
	except Exception as e:
		_raise_trade_execution_http_exception(err=e)
