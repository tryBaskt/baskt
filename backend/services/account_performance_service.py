# backend/services/account_performance_service.py

# Python imports
from __future__ import annotations
from typing import Dict, Any

# Baskt imports
from clients.alpaca_broker_client import AlpacaBrokerClient
from repository.portfolio_allocation_repository import PortfolioAllocationRepository

class AccountPerformanceServiceError(Exception):
	def __init__(self, message: str, code: str = "ACCOUNT_LIFECYCLE_SERVICE_ERROR") -> None:
		"""
		Initialize an account lifecycle service exception.

		Args:
			message: Human-readable error details.
			code: Stable error code identifying the failed operation.

		Returns:
			None.
		"""
		super().__init__(message)
		self.code = code

class AccountPerformanceService:
    def __init__(
        self,
        *,
        alpaca_broker_client: AlpacaBrokerClient,
        portfolio_allocation_repository: PortfolioAllocationRepository
    ):
        self.alpaca_broker_client = alpaca_broker_client
        self.portfolio_allocation_repository = portfolio_allocation_repository

    def get_portfolio_allocation_transactions(self, cognito_user_id: str, portfolio_id: str):

        try:
            allocation_snapshots = self.portfolio_allocation_repository.get_portfolio_allocation_history(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id)
        except Exception as e:
            raise AccountPerformanceServiceError(
                message=f"Failed to get portfolio allocation history for model portfolio '{portfolio_id}' for cognito user id '{cognito_user_id}': {e}",
                code="ACCOUNT_PERFORMANCE_GET_TRANSACTIONS_FAILED"
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
            raise AccountPerformanceServiceError(
                message=f"Failed to get portfolio allocation transaction for model portfolio '{portfolio_id}' for cognito user id '{cognito_user_id}': {e}",
                code="ACCOUNT_PERFORMANCE_GET_TRANSACTIONS_FAILED"
            ) from e




        



    def get_account_performance(self, alpaca_account_id: str) -> Dict[str, Dict[str, Any]]:

        account_performance = self.alpaca_broker_client.get_account_performance(alpaca_account_id=alpaca_account_id)

        return account_performance
    
    def get_portfolio_allocation_performance(self, cognito_user_id: str, portfolio_id: str):
        if not self.portfolio_allocation_repository.is_exists_portfolio_allocation_for_user(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id):
            return None

        snapshots = self.portfolio_allocation_repository.get_n_last_portfolio_allocation_snapshots(cognito_user_id=cognito_user_id, portfolio_id=portfolio_id, n = 1)
        current_snapshot = snapshots[-1]

        _, current_value, _ = self.portfolio_allocation_repository.calculate_positions_current_value(
            portfolio_allocation_snapshot=current_snapshot,
        )

        allocation_amount = current_snapshot.allocation_amount

        profit_loss = current_value - allocation_amount
        profit_loss_pct = profit_loss / allocation_amount if allocation_amount else 0.0

        return {
            "current_value": current_value,
            "allocation_amount": allocation_amount,
            "profit_loss": profit_loss,
            "profit_loss_pct": profit_loss_pct
        }
        

