
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Dict
from fastapi import HTTPException
from domain.portfolio_allocation import PortfolioAllocationPosition, PortfolioAllocationSnapshot, PortfolioAllocation
from domain.model_portfolio import ModelPortfolioSnapshot, ModelPortfolioPosition, DeltaPosition
from domain.baskt import BasktPosition
from repository.model_portfolio_repository import ModelPortfolioRepository
from repository.portfolio_allocation_repository import PortfolioAllocationRepository
from repository.order_repository import OrderRepository
from repository.model_portfolio_follower_repository import ModelPortfolioFollowerRepository
from repository.user_trade_lock_repository import UserTradeLockRepository
from repository.user_account_repository import UserAccountRepository
from alpaca.trading.models import Order
from services.account_lifecycle_service import AccountLifecycleService, AccountLifecycleServiceError
import uuid
from math import floor, ceil
from clients.alpaca_broker_client import AlpacaBrokerClient
from domain.baskt import BasktAccount
MARGIN = 0.0007
EPS = 1e-6
LOCK_LEASE_SECONDS = 30

class AccountPerformanceService:
    def __init__(
        self,
        *,
        alpaca_broker_client: AlpacaBrokerClient,
        user_account_repository: UserAccountRepository
    ):
        self.alpaca_broker_client = alpaca_broker_client
        self.user_account_repository = user_account_repository

    def get_account_equity_graph(self, cognito_user_id: str):
        user_account = self.user_account_repository.get_user_account_by_cognito_user_id(
            cognito_user_id=cognito_user_id
        )
        alpaca_account_id = user_account["alpaca_account_id"]
        history = self.alpaca_broker_client.get_portfolio_history_for_account(
            alpaca_account_id=alpaca_account_id
        )
        return {
            "equity": history.equity,
            "timestamp": history.timestamp,
        }
