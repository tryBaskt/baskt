# backend/services/investment_analytics_service.py

# Python imports
from __future__ import annotations
from typing import Dict, Any, List

# Baskt imports
from clients.alpaca_broker_client import AlpacaBrokerClient
from repository.allocation_repository import AllocationRepository
from domain.allocation_domain import PortfolioAllocationTransactionSnapshot
from domain.stock_domain import Stock


class InvestmentAnalyticsInternalServerError(Exception):
	def __init__(self, message: str, code: str = "INVESTMENT_ANALYTICS_SERVICE_ERROR") -> None:
		"""
		Initialize an investment analytics service exception.

		Args:
			message: Human-readable error details.
			code: Stable error code identifying the failed operation.

		Returns:
			None.
		"""
		super().__init__(message)
		self.code = code

class InvestmentAnalyticsService:
    def __init__(
        self,
        *,
        alpaca_broker_client: AlpacaBrokerClient,
        allocation_repository: AllocationRepository,
    ):
        self.alpaca_broker_client = alpaca_broker_client
        self.allocation_repository = allocation_repository

    def get_portfolio_allocation_analytics(self, cognito_user_id: str, portfolio_id: str, is_stock_allocation: bool = False) -> Dict[str, Any]:

        try:
            if not self.allocation_repository.is_exists_allocation_for_user(cognito_user_id=cognito_user_id, allocation_id=portfolio_id):
                return {}

            portfolio_allocation = self.allocation_repository.get_allocation(cognito_user_id=cognito_user_id, allocation_id=portfolio_id)
            position_history = portfolio_allocation.position_history
            if (not position_history) or (not position_history[-1].positions):
                return {
                    "total_cost_basis": 0.0,
                    "equity": 0.0,
                    "profit_loss": 0.0,
                    "profit_loss_percent": 0.0,
                    "direction": None

                }
            total_cost_basis = portfolio_allocation.total_cost_basis
            _, equity, _ = self.allocation_repository.calculate_positions_current_value(portfolio_allocation_position_snapshot=portfolio_allocation.position_history[-1])
            return {
                "total_cost_basis": total_cost_basis,
                "equity": equity,
                "profit_loss": equity - total_cost_basis,
                "profit_loss_percent": (equity - total_cost_basis) / total_cost_basis,
                "direction": portfolio_allocation.position_history[-1].positions[0].direction if is_stock_allocation else None
            }
        except Exception as e:
            raise InvestmentAnalyticsInternalServerError(
                message=f"Failed to get investment analytics for model portfolio '{portfolio_id}' for cognito user id '{cognito_user_id}': {e}",
                code="INVESTMENT_ANALYTICS_GET_PORTFOLIO_ALLOCATION_ANALYTICS_FAILED"
            ) from e
        
    def get_stock_by_stock_id(self, stock_id: str) -> Stock:
        try:
            return self.alpaca_broker_client.get_stock_by_asset_id(asset_id=stock_id)
        except Exception as e:
            raise InvestmentAnalyticsInternalServerError(
                message=f"Failed to get investment analytics stock for stock id '{stock_id}': {e}",
                code="INVESTMENT_ANALYTICS_GET_STOCK__FAILED"
            )

        
    def get_portfolio_allocation_transactions(self, cognito_user_id: str, portfolio_id: str) -> List[PortfolioAllocationTransactionSnapshot]:
         
        try:
            if not self.allocation_repository.is_exists_allocation_for_user(cognito_user_id=cognito_user_id, allocation_id=portfolio_id):
                return []
            
            return self.allocation_repository.get_portfolio_allocation_transaction_history(cognito_user_id=cognito_user_id, allocation_id=portfolio_id)
        
        except Exception as e:
            raise InvestmentAnalyticsInternalServerError(
                message=f"Failed to get investment analytics portfolio allocation transactions for model portfolio '{portfolio_id}' for cognito user id '{cognito_user_id}': {e}",
                code="ACCOUNT_ANALYTICS_GET_TRANSACTIONS_FAILED"
            )


    def get_account_analytics(self, cognito_user_id: str, alpaca_account_id: str) -> Dict[str, Any]:
        try:
            account_analytics = {}

            portfolio_history_dict = self.alpaca_broker_client.get_portfolio_history(alpaca_account_id=alpaca_account_id)
            equity_graph_dict = {}
            for period in portfolio_history_dict:
                portfolio_history = portfolio_history_dict[period]
                equity_graph_dict[period] = {
                    "equity": portfolio_history.equity,
                    "timestamp": portfolio_history.timestamp # Equity and timestamp is for the equity graph
                }
            account_analytics["equity_graph"] = equity_graph_dict

            trade_account = self.alpaca_broker_client.get_trade_account(account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
            account_analytics["cash"] = float(trade_account.cash)
            account_analytics["equity"] = float(trade_account.equity)

            account_analytics["portfolio_allocations"] = {}
            portfolio_allocations = self.allocation_repository.get_allocations_by_cognito_user_id(cognito_user_id=cognito_user_id)
            for portfolio_allocation in portfolio_allocations:
                if (
                    portfolio_allocation.transaction_history
                    and portfolio_allocation.transaction_history[-1].transaction_type in ("CLOSE", "WITHDRAW_ALL")
                    and portfolio_allocation.transaction_history[-1].status in ("FULLY_FILLED")
                ):
                    continue

                portfolio_allocation_equity = 0.0
                if portfolio_allocation.position_history:
                    curr_port_alloc_pos_snapshot = portfolio_allocation.position_history[-1]
                    if curr_port_alloc_pos_snapshot.positions:
                        _, portfolio_allocation_equity, _ = self.allocation_repository.calculate_positions_current_value(portfolio_allocation_position_snapshot=curr_port_alloc_pos_snapshot)

                allocation_name = (
                    portfolio_allocation.symbol
                    if portfolio_allocation.allocation_type == "STOCK"
                    else portfolio_allocation.portfolio_name
                )
                account_analytics["portfolio_allocations"][portfolio_allocation.allocation_id] = {
                    "portfolio_name": allocation_name,
                    "portfolio_id": portfolio_allocation.allocation_id,
                    "allocation_type": portfolio_allocation.allocation_type,
                    "portfolio_allocation_equity": portfolio_allocation_equity,
                    "portfolio_allocation_equity_percent": portfolio_allocation_equity / float(trade_account.equity) if float(trade_account.equity) > 0.0 else 0.0
                }
            return account_analytics
        
        except Exception as err:
            raise InvestmentAnalyticsInternalServerError(
                message=f"Failed to get investment analytics for alpaca account id '{alpaca_account_id}': {err}"
            ) from err

        
