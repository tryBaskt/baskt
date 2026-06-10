
from __future__ import annotations

from typing import List, Dict, Any

from clients.alpaca_broker_client import AlpacaBrokerClient
from repository.portfolio_allocation_repository import PortfolioAllocationRepository

class AccountPerformanceService:
    def __init__(
        self,
        *,
        alpaca_broker_client: AlpacaBrokerClient,
        portfolio_allocation_repository: PortfolioAllocationRepository
    ):
        self.alpaca_broker_client = alpaca_broker_client
        self.portfolio_allocation_repository = portfolio_allocation_repository

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
        

