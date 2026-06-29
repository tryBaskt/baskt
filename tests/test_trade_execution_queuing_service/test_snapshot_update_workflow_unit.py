import json
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

from domain.model_portfolio_domain import ModelPortfolio, ModelPortfolioSnapshot
from domain.portfolio_allocation_domain import (
    PortfolioAllocation,
    PortfolioAllocationTransactionSnapshot,
)
from repository.portfolio_allocation_repository import (
    _parse_transaction_snapshot,
    _serialize_transaction_snapshot,
)
from services.trade_execution_queuing_service import TradeExecutionQueuingService


class FakeSQSClient:
    def __init__(self) -> None:
        self.messages = []

    def send_message(self, *, QueueUrl, MessageBody):
        self.messages.append(json.loads(MessageBody))
        return {"MessageId": "message-1"}


class FakeAllocationRepository:
    def __init__(self, allocation: PortfolioAllocation) -> None:
        self.allocation = deepcopy(allocation)

    def is_exists_portfolio_allocation_for_user(self, cognito_user_id, portfolio_id):
        return True

    def get_portfolio_allocation(self, cognito_user_id, portfolio_id, with_wait=False):
        return deepcopy(self.allocation)

    def set_portfolio_allocation(self, portfolio_allocation):
        self.allocation = deepcopy(portfolio_allocation)


class FakeLockRepository:
    def acquire_lock(self, cognito_user_id, owner_token, lease_seconds):
        return True

    def release_lock(self, cognito_user_id, owner_token):
        return True


def test_queue_portfolio_update_persists_and_publishes_snapshot_id():
    now = datetime.now(timezone.utc)
    snapshot = ModelPortfolioSnapshot(
        positions=[],
        timestamp=now,
        snapshot_id="snapshot-1",
    )
    model_portfolio = ModelPortfolio(
        portfolio_id="portfolio-1",
        portfolio_owner_cognito_user_id="owner-1",
        portfolio_name="Portfolio",
        position_history=[snapshot],
        created_at=now,
        updated_at=now,
    )
    allocation_repository = FakeAllocationRepository(
        PortfolioAllocation(
            portfolio_id="portfolio-1",
            cognito_user_id="user-1",
            position_history=[],
            transaction_history=[],
            total_cost_basis=0.0,
            portfolio_allocation_type="MODEL_PORTFOLIO",
            portfolio_name="Portfolio",
        )
    )
    sqs_client = FakeSQSClient()
    service = TradeExecutionQueuingService(
        sqs_client=sqs_client,
        queue_url="mock-queue",
        model_portfolio_repository=SimpleNamespace(
            get_model_portfolio=lambda portfolio_id: model_portfolio
        ),
        portfolio_allocation_repository=allocation_repository,
        alpaca_broker_client=SimpleNamespace(),
        user_trade_lock_repository=FakeLockRepository(),
        model_portfolio_follower_repository=SimpleNamespace(
            get_model_portfolio_followers=lambda portfolio_id: [
                {
                    "cognito_user_id": "user-1",
                    "alpaca_account_id": "account-1",
                }
            ]
        ),
    )

    message_ids = service.queue_portfolio_update(
        portfolio_id="portfolio-1",
        model_portfolio_snapshot_id="snapshot-1",
    )

    transaction = allocation_repository.allocation.transaction_history[-1]
    payload = sqs_client.messages[-1]["payload"]
    assert message_ids == {"user-1": "message-1"}
    assert transaction.model_portfolio_snapshot_id == "snapshot-1"
    assert payload["model_portfolio_snapshot_id"] == "snapshot-1"
    assert payload["transaction_id"] == transaction.transaction_id


def test_transaction_snapshot_round_trip_preserves_optional_model_snapshot_id():
    now = datetime.now(timezone.utc)
    transaction = PortfolioAllocationTransactionSnapshot(
        transaction_id="transaction-1",
        created_at=now,
        updated_at=now,
        requested_amount=None,
        transaction_type="UPDATE",
        status="QUEUED",
        model_portfolio_snapshot_id="snapshot-1",
    )

    restored = _parse_transaction_snapshot(_serialize_transaction_snapshot(transaction))

    assert restored == transaction
