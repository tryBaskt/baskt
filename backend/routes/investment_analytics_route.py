# backend/routes/account_analytics_route.py

# Python imports
from __future__ import annotations
from typing import Dict, Any, Optional
from starlette.status import HTTP_200_OK, HTTP_500_INTERNAL_SERVER_ERROR
# Fastapi imports
from fastapi import APIRouter, Depends, HTTPException
# Alpaca imports
from alpaca.broker.models import Account
# Baskt imports
from core.deps import (
	get_investment_analytics_service,
	get_current_user,
	get_current_active_alpaca_account,
	get_trade_execution_service,
	get_order_repository
)
from repository.order_repository import OrderRepository
from schema.investment_analytics_schema import (
	AccountAnalyticsResponse,
	EquityGraphResponse
)
from schema.stock_schema import (
	StockResponse,
	StockAllocationResponse,
	StockAllocationTransactionResponse
)
from schema.portfolio_allocation_schema import (
	PortfolioAllocationTransactionResponse,
	PortfolioAllocationResponse
)
from services.investment_analytics_service import (
	InvestmentAnalyticsInternalServerError,
	InvestmentAnalyticsService,
)
from services.trade_execution_service import (
	TradeExecutionInternalServerError,
	TradeExecutionService,
)



router = APIRouter(prefix="/account-analytics", tags=["account-performance"])


def _raise_investment_analytics_http_exception(err: Exception) -> None:
    if isinstance(err, HTTPException):
        raise err

    if isinstance(
        err,
        (InvestmentAnalyticsInternalServerError, TradeExecutionInternalServerError),
    ):
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": str(err), "code": err.code},
        ) from err

    raise HTTPException(
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "message": f"Unexpected account analytics error: {err}",
            "code": "INVESTMENT_ANALYTICS_UNEXPECTED_ERROR",
        },
    ) from err


@router.get("", response_model= AccountAnalyticsResponse, status_code=HTTP_200_OK)
def get_account_analytics(
	user: Dict[str, Any] = Depends(get_current_user),
	active_alpaca_account: Account = Depends(get_current_active_alpaca_account),
	service: InvestmentAnalyticsService = Depends(get_investment_analytics_service),
	trade_execution_service: TradeExecutionService = Depends(get_trade_execution_service),
	order_repository: OrderRepository = Depends(get_order_repository)
) -> AccountAnalyticsResponse:
	cognito_user_id = user["sub"]
	alpaca_account_id = user["custom:alpaca_acct_id"]

	try:
		portfolio_ids_owner_ids = order_repository.get_portfolio_ids_of_unfilled_orders(cognito_user_id=cognito_user_id)

		for portfolio_id, portfolio_owner_cognito_user_id in portfolio_ids_owner_ids:
			trade_execution_service.realize_filled_orders(
				cognito_user_id=cognito_user_id,
				alpaca_account_id=alpaca_account_id,
				portfolio_id=portfolio_id,
				portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
				lock_already_acquired=False
			)

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
		_raise_investment_analytics_http_exception(err=err)




@router.get("/portfolios/{portfolio_id}/analytics", response_model=PortfolioAllocationResponse, status_code=HTTP_200_OK)
def get_portfolio_allocation_analytics(
	portfolio_id: str,
	portfolio_owner_cognito_user_id: str,
	user: Dict[str, Any] = Depends(get_current_user),
	active_alpaca_account: Account = Depends(get_current_active_alpaca_account),
	service: InvestmentAnalyticsService = Depends(get_investment_analytics_service),
	trade_execution_service: TradeExecutionService = Depends(get_trade_execution_service),
) -> PortfolioAllocationResponse:

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
		transactions = service.get_portfolio_allocation_transactions(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id)
		if not analytics_dict and not transactions:
			return PortfolioAllocationResponse(portfolio_id=portfolio_id)

		transactions_response = [
			PortfolioAllocationTransactionResponse(
				transaction_id=transaction.transaction_id,
				model_portfolio_snapshot_id=transaction.model_portfolio_snapshot_id,
				created_at=transaction.created_at,
				filled_at=transaction.filled_at,
				updated_at=transaction.updated_at,
				requested_amount=transaction.requested_amount,
				number_orders=transaction.number_orders,
				transaction_type=transaction.transaction_type,
				cost_basis=transaction.cost_basis,
				order_fill_percent=transaction.order_fill_percent,
				status=transaction.status,
				status_explanation=transaction.status_explanation,
			)
			for transaction in transactions
		]

		return PortfolioAllocationResponse(
			portfolio_id=portfolio_id,
			transaction_history=transactions_response,
			total_cost_basis=analytics_dict["total_cost_basis"],
			equity=analytics_dict["equity"],
			profit_loss=analytics_dict["profit_loss"],
			profit_loss_percent=analytics_dict["profit_loss_percent"]
		)

	except Exception as e:
		_raise_investment_analytics_http_exception(err=e)


@router.get("/stocks/{stock_id}/analytics", response_model=StockAllocationResponse, status_code=HTTP_200_OK)
def get_stock_allocation_analytics(
	stock_id: str,
	portfolio_owner_cognito_user_id: Optional[str] = None,
	user: Dict[str, Any] = Depends(get_current_user),
	active_alpaca_account: Account = Depends(get_current_active_alpaca_account),
	service: InvestmentAnalyticsService = Depends(get_investment_analytics_service),
	trade_execution_service: TradeExecutionService = Depends(get_trade_execution_service),
) -> StockAllocationResponse:

	cognito_user_id = user["sub"]
	alpaca_account_id = user["custom:alpaca_acct_id"]

	try:
		trade_execution_service.realize_filled_orders(
			cognito_user_id=cognito_user_id,
			alpaca_account_id=alpaca_account_id,
			portfolio_id=stock_id,
			portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id
		)

		analytics_dict = service.get_portfolio_allocation_analytics(cognito_user_id=cognito_user_id,portfolio_id=stock_id)
		transactions = service.get_portfolio_allocation_transactions(cognito_user_id=cognito_user_id, portfolio_id=stock_id)
		if not analytics_dict and not transactions:
			return StockAllocationResponse(
				stock_id=stock_id
			)

		return StockAllocationResponse(
			stock_id=stock_id,
			transaction_history=[
				StockAllocationTransactionResponse(
					transaction_id=transaction.transaction_id,
					created_at=transaction.created_at,
					filled_at=transaction.filled_at,
					updated_at=transaction.updated_at,
					requested_amount=transaction.requested_amount,
					number_orders=transaction.number_orders,
					transaction_type=transaction.transaction_type,
					cost_basis=transaction.cost_basis,
					order_fill_percent=transaction.order_fill_percent,
					status=transaction.status,
					status_explanation=transaction.status_explanation,
				)
				for transaction in transactions
			],
			total_cost_basis=analytics_dict["total_cost_basis"],
			equity=analytics_dict["equity"],
			profit_loss=analytics_dict["profit_loss"],
			profit_loss_percent=analytics_dict["profit_loss_percent"]
		)

	except Exception as e:
		_raise_investment_analytics_http_exception(err=e)


@router.get("/stocks/{stock_id}", response_model=StockResponse, status_code=HTTP_200_OK)
def get_stock_metadata(
	stock_id: str,
	user: Dict[str, Any] = Depends(get_current_user),
	service: InvestmentAnalyticsService = Depends(get_investment_analytics_service),
) -> StockResponse:
	try:
		stock = service.get_stock_by_stock_id(stock_id=stock_id)

		return StockResponse(
			symbol=stock.symbol,
			tradable=stock.tradable,
			fractionable=stock.fractionable,
			shortable=stock.shortable,
			marginable=stock.marginable,
			stock_id=stock.stock_id,
			stock_class=stock.stock_class,
		)
	except Exception as e:
		_raise_investment_analytics_http_exception(err=e)
