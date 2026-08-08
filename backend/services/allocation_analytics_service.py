# backend/services/allocation_analytics_service.py

# Python imports
from __future__ import annotations
from typing import Dict, Any, List

# Baskt imports
from clients.alpaca_broker_client import AlpacaBrokerClient
from repository.allocation_repository import AllocationRepository
from domain.allocation_domain import (
    PortfolioAllocationTransactionSnapshot,
    StockAllocationPositionSnapshot,
    StockAllocationTransactionSnapshot,
)
from domain.stock_domain import Stock


class AllocationAnalyticsInternalServerError(Exception):
	def __init__(self, message: str, code: str = "ALLOCATION_ANALYTICS_SERVICE_ERROR") -> None:
		"""
		Initialize an allocation analytics service exception.

		Args:
			message: Human-readable error details.
			code: Stable error code identifying the failed operation.

		Returns:
			None.
		"""
		super().__init__(message)
		self.code = code

class AllocationAnalyticsService:
    def __init__(
        self,
        *,
        alpaca_broker_client: AlpacaBrokerClient,
        allocation_repository: AllocationRepository,
    ):
        self.alpaca_broker_client = alpaca_broker_client
        self.allocation_repository = allocation_repository

    def get_portfolio_allocation_analytics(self, cognito_user_id: str, portfolio_id: str) -> Dict[str, Any]:

        try:
            if not self.allocation_repository.is_exists_allocation_for_user(cognito_user_id=cognito_user_id, allocation_id=portfolio_id):
                return {}

            portfolio_allocation = self.allocation_repository.get_portfolio_allocation(cognito_user_id=cognito_user_id, allocation_id=portfolio_id)

            if not (portfolio_allocation.open_orders or portfolio_allocation.open_positions):
                return {}
            if portfolio_allocation.open_orders and not portfolio_allocation.open_positions:
                return {
                    "total_cost_basis": 0.00,
                    "equity": 0.00,
                    "profit_loss": 0.00,
                    "profit_loss_percent": 0.0
                }

            total_cost_basis = portfolio_allocation.total_cost_basis
            latest_position_snapshot = portfolio_allocation.position_history[-1]
            _, equity, _ = self.allocation_repository.calculate_portfolio_allocation_position_snapshot_current_value(position_snapshot=latest_position_snapshot)
            return {
                "total_cost_basis": total_cost_basis,
                "equity": equity,
                "profit_loss": equity - total_cost_basis,
                "profit_loss_percent": ((equity - total_cost_basis) / total_cost_basis) if total_cost_basis else 0.0
            }
        except Exception as e:
            raise AllocationAnalyticsInternalServerError(
                message=f"Failed to get allocation analytics for model portfolio '{portfolio_id}' for cognito user id '{cognito_user_id}': {e}",
                code="ALLOCATION_ANALYTICS_GET_PORTFOLIO_FAILED"
            ) from e

    def get_stock_allocation_analytics(self, cognito_user_id: str, stock_id: str) -> Dict[str, Any]:

        try:
            if not self.allocation_repository.is_exists_allocation_for_user(cognito_user_id=cognito_user_id, allocation_id=stock_id):
                return {}

            stock_allocation = self.allocation_repository.get_stock_allocation(cognito_user_id=cognito_user_id, allocation_id=stock_id)
            if not (stock_allocation.open_positions or stock_allocation.open_orders):
                return {}
            if stock_allocation.open_orders and not stock_allocation.open_positions:
                return {
                    "total_cost_basis": 0.00,
                    "equity": 0.00,
                    "profit_loss": 0.00,
                    "profit_loss_percent": 0.0,
                }
            
            total_cost_basis = stock_allocation.total_cost_basis
            latest_position_snapshot = stock_allocation.position_history[-1]
            equity, _ = self.allocation_repository.calculate_stock_allocation_position_snapshot_current_value(position_snapshot=latest_position_snapshot)
            return {
                "total_cost_basis": total_cost_basis,
                "equity": equity,
                "profit_loss": equity - total_cost_basis,
                "profit_loss_percent": ((equity - total_cost_basis) / total_cost_basis) if total_cost_basis else 0.0,
                "direction": latest_position_snapshot.position.direction
            }
        except Exception as e:
            raise AllocationAnalyticsInternalServerError(
                message=f"Failed to get allocation analytics for stock id '{stock_id}' for cognito user id '{cognito_user_id}': {e}",
                code="ALLOCATION_ANALYTICS_GET_STOCK_FAILED"
            ) from e

    def get_portfolio_allocation_transaction_history(self, cognito_user_id: str, portfolio_id: str) -> List[PortfolioAllocationTransactionSnapshot]:
         
        try:
            if not self.allocation_repository.is_exists_allocation_for_user(cognito_user_id=cognito_user_id, allocation_id=portfolio_id):
                return []
            
            return self.allocation_repository.get_portfolio_allocation_transaction_history(cognito_user_id=cognito_user_id, allocation_id=portfolio_id)
        
        except Exception as e:
            raise AllocationAnalyticsInternalServerError(
                message=f"Failed to get allocation transactions for model portfolio '{portfolio_id}' for cognito user id '{cognito_user_id}': {e}",
                code="ALLOCATION_ANALYTICS_GET_TRANSACTIONS_FAILED"
            )


    def get_stock_allocation_transaction_history(self, cognito_user_id: str, stock_id: str) -> List[StockAllocationTransactionSnapshot]:
         
        try:
            if not self.allocation_repository.is_exists_allocation_for_user(cognito_user_id=cognito_user_id, allocation_id=stock_id):
                return []
            
            return self.allocation_repository.get_stock_allocation_transaction_history(cognito_user_id=cognito_user_id, allocation_id=stock_id)
        
        except Exception as e:
            raise AllocationAnalyticsInternalServerError(
                message=f"Failed to get allocation transactions for stock id '{stock_id}' for cognito user id '{cognito_user_id}': {e}",
                code="ALLOCATION_ANALYTICS_GET_TRANSACTIONS_FAILED"
            )
        

    def get_all_active_allocation_analytics(self, cognito_user_id: str, alpaca_account_id: str) -> Dict[str, Any]:
        try:
            all_allocation_analytics = {}

            portfolio_history_dict = self.alpaca_broker_client.get_portfolio_history(alpaca_account_id=alpaca_account_id)
            equity_graph_dict = {}
            for period in portfolio_history_dict:
                portfolio_history = portfolio_history_dict[period]
                equity_graph_dict[period] = {
                    "equity": portfolio_history.equity,
                    "timestamp": portfolio_history.timestamp # Equity and timestamp is for the equity graph
                }
            all_allocation_analytics["equity_graph"] = equity_graph_dict

            trade_account = self.alpaca_broker_client.get_trade_account(account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
            all_allocation_analytics["cash"] = float(trade_account.cash)
            all_allocation_analytics["equity"] = float(trade_account.equity)

            all_allocation_analytics["allocations"] = {}
            allocations = self.allocation_repository.get_allocations_by_cognito_user_id(cognito_user_id=cognito_user_id)
            for allocation in allocations:
                if not (allocation.open_orders or allocation.open_positions):
                    continue

                allocation_equity = 0.0
                if allocation.open_positions:
                    latest_position_snapshot = allocation.position_history[-1]
                    if isinstance(latest_position_snapshot, StockAllocationPositionSnapshot):
                        allocation_equity, _ = self.allocation_repository.calculate_stock_allocation_position_snapshot_current_value(position_snapshot=latest_position_snapshot)
                    else:
                        _, allocation_equity, _ = self.allocation_repository.calculate_portfolio_allocation_position_snapshot_current_value(position_snapshot=latest_position_snapshot)

                allocation_name = (
                    allocation.symbol
                    if allocation.allocation_type == "STOCK"
                    else allocation.portfolio_name
                )

                all_allocation_analytics["allocations"][allocation.allocation_id] = {
                    "allocation_name": allocation_name,
                    "allocation_id": allocation.allocation_id,
                    "allocation_type": allocation.allocation_type,
                    "allocation_equity": allocation_equity,
                    "allocation_equity_percent": allocation_equity / float(trade_account.equity) if float(trade_account.equity) > 0.0 else 0.0
                }
            return all_allocation_analytics
        
        except Exception as err:
            raise AllocationAnalyticsInternalServerError(
                message=f"Failed to get all allocation analytics for alpaca account id '{alpaca_account_id}' and cognito user id '{cognito_user_id}': {err}"
            ) from err

        
