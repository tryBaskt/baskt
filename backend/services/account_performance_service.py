
from __future__ import annotations

from typing import List, Dict, Any

from clients.alpaca_broker_client import AlpacaBrokerClient

class AccountPerformanceService:
    def __init__(
        self,
        *,
        alpaca_broker_client: AlpacaBrokerClient,
    ):
        self.alpaca_broker_client = alpaca_broker_client

    def get_account_performance(self, alpaca_account_id: str) -> Dict[str, Dict[str, Any]]:

        account_performance = self.alpaca_broker_client.get_account_performance(alpaca_account_id=alpaca_account_id)

        return account_performance





