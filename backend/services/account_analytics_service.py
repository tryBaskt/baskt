# backend/services/account_analytics_service.py

# Python imports
from __future__ import annotations
from typing import Dict, Any, List, Optional

# Baskt imports
from clients.alpaca_broker_client import AlpacaBrokerClient
from repository.portfolio_allocation_repository import PortfolioAllocationRepository

class AccountAnalyticsServiceError(Exception):
	def __init__(self, message: str, code: str = "ACCOUNT_ANALYTICS_SERVICE_ERROR") -> None:
		"""
		Initialize an account analytics service exception.

		Args:
			message: Human-readable error details.
			code: Stable error code identifying the failed operation.

		Returns:
			None.
		"""
		super().__init__(message)
		self.code = code

class AccountAnalyticsService:
    def __init__(
        self,
        *,
        alpaca_broker_client: AlpacaBrokerClient,
        portfolio_allocation_repository: PortfolioAllocationRepository
    ):
        self.alpaca_broker_client = alpaca_broker_client
        self.portfolio_allocation_repository = portfolio_allocation_repository

    def get_portfolio_allocation_transactions(self, cognito_user_id: str, portfolio_id: str) -> List[Optional[Dict[str, str | float]]]:

        try:
            if not self.portfolio_allocation_repository.is_exists_portfolio_allocation_for_user(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id):
                 return []
            allocation_snapshots = self.portfolio_allocation_repository.get_portfolio_allocation_history(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id)
        except Exception as e:
            raise AccountAnalyticsServiceError(
                message=f"Failed to get portfolio allocation history for model portfolio '{portfolio_id}' for cognito user id '{cognito_user_id}': {e}",
                code="ACCOUNT_ANALYTICS_GET_TRANSACTIONS_FAILED"
            ) from e

        res = []
        prev_allocation_amount = 0.0
        try:
            for snapshot in allocation_snapshots:
                delta = snapshot.allocation_amount - prev_allocation_amount
                res.append(
                    {
                        "transaction_id": snapshot.transaction_id,
                        "transaction_amount": abs(delta),
                        "transaction_date": snapshot.timestamp.isoformat(),
                        "transaction_type": snapshot.transaction_type,
                        "transaction_filled_percent": snapshot.order_fill_percent
                    }
                )
                prev_allocation_amount = snapshot.allocation_amount
            return res
        except Exception as e:
            raise AccountAnalyticsServiceError(
                message=f"Failed to get portfolio allocation transaction for model portfolio '{portfolio_id}' for cognito user id '{cognito_user_id}': {e}",
                code="ACCOUNT_ANALYTICS_GET_TRANSACTIONS_FAILED"
            ) from e


    def get_account_analytics(self, cognito_user_id: str, alpaca_account_id: str) -> Dict[str, Any]:

        try:
            portfolio_history_dict = self.alpaca_broker_client.get_portfolio_history(alpaca_account_id=alpaca_account_id)
            trade_account = self.alpaca_broker_client.get_trade_account(account_id=alpaca_account_id, cognito_user_id=cognito_user_id)
            equity_graph_dict = {}
            for period in portfolio_history_dict:
                portfolio_history = portfolio_history_dict[period]
                equity_graph_dict[period] = {
                    "equity": portfolio_history.equity,
                    "timestamp": portfolio_history.timestamp # Equity and timestamp is for the equity graph
                }
            account_analytics = {}
            account_analytics["cash"] = trade_account.cash
            account_analytics["equity"] = trade_account.equity
            account_analytics["equity_graph"] = equity_graph_dict

            return account_analytics
        
        except Exception as err:
            raise AccountAnalyticsServiceError(
                message=f"Failed to get account analytics for alpaca account id '{alpaca_account_id}': {err}"
            ) from err

        

