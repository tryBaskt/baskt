
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Dict, Any
from fastapi import HTTPException
from domain.portfolio_allocation import PortfolioAllocationPosition, PortfolioAllocationSnapshot, PortfolioAllocation
from domain.model_portfolio import ModelPortfolioSnapshot, ModelPortfolioPosition, DeltaPosition
from domain.baskt import BasktPosition
from repository.model_portfolio_repository import ModelPortfolioRepository
from repository.portfolio_allocation_repository import PortfolioAllocationRepository
from repository.order_repository import OrderRepository
from repository.model_portfolio_follower_repository import ModelPortfolioFollowerRepository
from repository.user_trade_lock_repository import UserTradeLockRepository
from alpaca.trading.models import Order
from services.account_lifecycle_service import AccountLifecycleService, AccountLifecycleServiceError
import uuid
from math import floor, ceil
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





