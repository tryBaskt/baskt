
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
    ):
        self.alpaca_broker_client = alpaca_broker_client


