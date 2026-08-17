from __future__ import annotations

from datetime import datetime, timedelta, timezone
from time import monotonic, sleep
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.tests_v2.mock_alpaca.trading import MockSQSClient
from core.authentication import (
    get_current_alpaca_account,
    get_current_baskt_account,
    get_current_user,
)
from core.deps import (
    get_allocation_repository,
    get_baskt_account_repository,
    get_model_portfolio_access_repository,
    get_model_portfolio_repository,
    get_trade_execution_queuing_service,
)
from domain.baskt_account_domain import BasktAccount
from repository.allocation_repository import AllocationRepository
from repository.baskt_account_repository import BasktAccountRepository
from repository.model_portfolio_access_repository import (
    ModelPortfolioAccessRepository,
)
from repository.model_portfolio_follower_repository import (
    ModelPortfolioFollowerRepository,
)
from repository.model_portfolio_repository import ModelPortfolioRepository
from repository.model_portfolio_update_lock_repository import (
    ModelPortfolioUpdateLockRepository,
)
from repository.order_repository import OrderRepository
from repository.user_trade_lock_repository import UserTradeLockRepository
from routes import model_portfolio_route, trade_execution_route
from schema.model_portfolio_schema import ModelPortfolioPositionRequest
from services.account_lifecycle_service import AccountLifecycleService
from services.trade_execution_queuing_service import TradeExecutionQueuingService
from services.trade_execution_service import TradeExecutionService


pytestmark = pytest.mark.integration


"""
These workflow tests exercise trade_execution_route.py through FastAPI's
TestClient with real tests_v2 repositories. Passing --mock_alpaca swaps Alpaca
trading and SQS for the in-memory mock stack so the same route workflows can run
after hours; without --mock_alpaca the tests use the live configured Alpaca/SQS
dependencies.

Coverage goals:
- Request validation: missing amounts and non-positive amounts are rejected by
  route/schema validation for portfolio and stock trade routes.
- Queue validation: below-minimum amounts are rejected through the real queuing
  service with HTTP 422.
- Authorization: private model portfolio trades are denied when the user has no
  owner, public, explicit-access, or follower/unwind relationship.
- Account authorization: inactive Alpaca accounts are rejected for portfolio
  deposit, withdrawal, withdraw-all, stock buy, stock sell, and stock close.
- Portfolio trade workflows: deposit, partial withdrawal, and withdraw-all go
  through the route, queue, execution service, repositories, and Alpaca/mock
  orders, with transaction and order artifacts verified.
- Stock trade workflows: buy, sell, and close go through the route, queue,
  execution service, repositories, and Alpaca/mock orders.
- Queue lock mapping: a real user trade lock maps to HTTP 409.
- Follower and allocation-access lifecycle: non-owner deposits into public or
  explicitly shared private portfolios create follower records; public deposits
  create ALLOCATION access records; partial withdrawals keep followers and
  access records; withdraw-all removes followers and allocation-only access.
- Public-to-private unwind lifecycle: a user who deposited into a public
  portfolio can withdraw after it becomes private; the visibility change marks
  ALLOCATION access TO_BE_DELETED, and withdraw-all removes the follower and
  access record. The owner never grants explicit access in that case.
- Authentication: token Alpaca-account mismatches and unknown token Cognito user
  ids are rejected by the real Baskt account auth dependency before queueing.

Every portfolio, follower, access, allocation, order, and trade-lock item
created here is cleaned up in finally blocks. Live mode also attempts to cancel
open orders and close positions for traded accounts during cleanup.
"""


CREATED_AT = datetime(2024, 1, 2, 14, tzinfo=timezone.utc)
UPDATE_AFTER_COOLDOWN = CREATED_AT + timedelta(minutes=2)
POLL_TIMEOUT_SECONDS = 60.0


def _delete_user_trade_lock(
    *,
    user_trade_lock_repository: UserTradeLockRepository,
    cognito_user_id: str,
) -> None:
    try:
        user_trade_lock_repository.lock_table_client.delete_item(
            key={"cognito_user_id": cognito_user_id}
        )
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _isolate_trade_execution_workflow_state(
    sqs_client: Any,
    trade_execution_service: TradeExecutionService,
    user_trade_lock_repository: UserTradeLockRepository,
    test_user_1: Any,
    test_user_2: Any,
):
    if _is_mock_sqs(sqs_client):
        sqs_client.reset()
        reset_trading_state = getattr(
            trade_execution_service.alpaca_broker_client,
            "reset_trading_state",
            None,
        )
        if callable(reset_trading_state):
            reset_trading_state()

    for test_user in (test_user_1, test_user_2):
        _delete_user_trade_lock(
            user_trade_lock_repository=user_trade_lock_repository,
            cognito_user_id=test_user.cognito_user_id,
        )

    yield

    if _is_mock_sqs(sqs_client):
        try:
            sqs_client.wait_until_idle()
        except Exception:
            pass
        sqs_client.reset()
        reset_trading_state = getattr(
            trade_execution_service.alpaca_broker_client,
            "reset_trading_state",
            None,
        )
        if callable(reset_trading_state):
            reset_trading_state()

    for test_user in (test_user_1, test_user_2):
        _delete_user_trade_lock(
            user_trade_lock_repository=user_trade_lock_repository,
            cognito_user_id=test_user.cognito_user_id,
        )


def _claims_for_user(test_user: Any) -> dict[str, str]:
    return {
        "sub": test_user.cognito_user_id,
        "custom:alpaca_acct_id": test_user.alpaca_account_id,
    }


def _claims_with_mismatched_alpaca_account(test_user: Any) -> dict[str, str]:
    return {
        "sub": test_user.cognito_user_id,
        "custom:alpaca_acct_id": f"tests-v2-wrong-alpaca-{uuid4()}",
    }


def _claims_with_mismatched_cognito_user_id(test_user: Any) -> dict[str, str]:
    return {
        "sub": f"tests-v2-wrong-cognito-{uuid4()}",
        "custom:alpaca_acct_id": test_user.alpaca_account_id,
    }


def _client_for_user(
    *,
    test_user: Any,
    baskt_account: BasktAccount,
    alpaca_account: Any,
    trade_execution_queuing_service: TradeExecutionQueuingService,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    allocation_repository: AllocationRepository,
    baskt_account_repository: BasktAccountRepository,
) -> TestClient:
    app = FastAPI()
    app.include_router(trade_execution_route.router)
    app.include_router(model_portfolio_route.router)
    app.dependency_overrides[get_current_user] = lambda: _claims_for_user(test_user)
    app.dependency_overrides[trade_execution_route.get_current_baskt_account] = (
        lambda: baskt_account
    )
    app.dependency_overrides[trade_execution_route.get_current_alpaca_account] = (
        lambda: alpaca_account
    )
    app.dependency_overrides[model_portfolio_route.get_current_baskt_account] = (
        lambda: baskt_account
    )
    app.dependency_overrides[get_current_baskt_account] = lambda: baskt_account
    app.dependency_overrides[get_current_alpaca_account] = lambda: alpaca_account
    app.dependency_overrides[
        trade_execution_route.get_trade_execution_queuing_service
    ] = lambda: trade_execution_queuing_service
    app.dependency_overrides[get_trade_execution_queuing_service] = (
        lambda: trade_execution_queuing_service
    )
    app.dependency_overrides[trade_execution_route.get_model_portfolio_repository] = (
        lambda: model_portfolio_repository
    )
    app.dependency_overrides[model_portfolio_route.get_model_portfolio_repository] = (
        lambda: model_portfolio_repository
    )
    app.dependency_overrides[get_model_portfolio_repository] = (
        lambda: model_portfolio_repository
    )
    app.dependency_overrides[
        trade_execution_route.get_model_portfolio_access_repository
    ] = lambda: model_portfolio_access_repository
    app.dependency_overrides[
        model_portfolio_route.get_model_portfolio_access_repository
    ] = lambda: model_portfolio_access_repository
    app.dependency_overrides[get_model_portfolio_access_repository] = (
        lambda: model_portfolio_access_repository
    )
    app.dependency_overrides[get_allocation_repository] = lambda: allocation_repository
    app.dependency_overrides[model_portfolio_route.get_baskt_account_repository] = (
        lambda: baskt_account_repository
    )
    app.dependency_overrides[get_baskt_account_repository] = (
        lambda: baskt_account_repository
    )
    return TestClient(app)


def _client_for_claims(
    *,
    claims: dict[str, str],
    trade_execution_queuing_service: TradeExecutionQueuingService,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    allocation_repository: AllocationRepository,
    baskt_account_repository: BasktAccountRepository,
) -> TestClient:
    app = FastAPI()
    app.include_router(trade_execution_route.router)
    app.dependency_overrides[get_current_user] = lambda: claims
    app.dependency_overrides[
        trade_execution_route.get_trade_execution_queuing_service
    ] = lambda: trade_execution_queuing_service
    app.dependency_overrides[get_trade_execution_queuing_service] = (
        lambda: trade_execution_queuing_service
    )
    app.dependency_overrides[trade_execution_route.get_model_portfolio_repository] = (
        lambda: model_portfolio_repository
    )
    app.dependency_overrides[get_model_portfolio_repository] = (
        lambda: model_portfolio_repository
    )
    app.dependency_overrides[
        trade_execution_route.get_model_portfolio_access_repository
    ] = lambda: model_portfolio_access_repository
    app.dependency_overrides[get_model_portfolio_access_repository] = (
        lambda: model_portfolio_access_repository
    )
    app.dependency_overrides[get_allocation_repository] = lambda: allocation_repository
    app.dependency_overrides[get_baskt_account_repository] = (
        lambda: baskt_account_repository
    )
    return TestClient(app)


def _baskt_account(
    *,
    account_lifecycle_service: AccountLifecycleService,
    test_user: Any,
) -> BasktAccount:
    return account_lifecycle_service.get_baskt_account(test_user.cognito_user_id)


def _alpaca_account(
    *,
    account_lifecycle_service: AccountLifecycleService,
    trade_execution_service: TradeExecutionService,
    test_user: Any,
) -> Any:
    return trade_execution_service.alpaca_broker_client.get_alpaca_account_by_id(
        account_id=test_user.alpaca_account_id,
        cognito_user_id=test_user.cognito_user_id,
    )


def _inactive_alpaca_account(test_user: Any) -> Any:
    return SimpleNamespace(
        id=test_user.alpaca_account_id,
        status=SimpleNamespace(name="INACTIVE"),
    )


def _create_model_portfolio(
    *,
    model_portfolio_repository: ModelPortfolioRepository,
    owner_cognito_user_id: str,
    visibility: str,
    positions: list[ModelPortfolioPositionRequest] | None = None,
) -> str:
    return model_portfolio_repository.create_model_portfolio(
        portfolio_owner_cognito_user_id=owner_cognito_user_id,
        portfolio_name=f"trade-route-workflow-{uuid4()}",
        positions_request=positions
        or [
            ModelPortfolioPositionRequest(
                symbol="AAPL",
                target_weight=1.0,
                direction=1,
                leverage=1.0,
            )
        ],
        visibility=visibility,
        creation_time=CREATED_AT,
        description="Trade execution workflow portfolio",
    )


def _make_private(
    *,
    model_portfolio_repository: ModelPortfolioRepository,
    portfolio_id: str,
) -> None:
    model_portfolio_repository.update_model_portfolio(
        portfolio_id=portfolio_id,
        positions_request=[
            ModelPortfolioPositionRequest(
                symbol="AAPL",
                target_weight=1.0,
                direction=1,
                leverage=1.0,
            )
        ],
        visibility="PRIVATE",
        update_time=UPDATE_AFTER_COOLDOWN,
        description="Trade execution workflow portfolio",
    )


def _stock_asset_id(
    *,
    trade_execution_service: TradeExecutionService,
    symbol: str = "AAPL",
) -> str:
    return trade_execution_service.alpaca_broker_client.get_stock_by_symbol(
        symbol=symbol
    ).stock_id


def _is_mock_sqs(sqs_client: Any) -> bool:
    return isinstance(sqs_client, MockSQSClient)


def _transaction_ids(
    *,
    allocation_repository: AllocationRepository,
    cognito_user_id: str,
    allocation_id: str,
) -> set[str]:
    if not allocation_repository.is_exists_allocation_for_user(
        cognito_user_id=cognito_user_id,
        allocation_id=allocation_id,
    ):
        return set()
    allocation = allocation_repository.get_allocation(
        cognito_user_id=cognito_user_id,
        allocation_id=allocation_id,
    )
    return {
        transaction.transaction_id
        for transaction in allocation.transaction_history
    }


def _wait_for_new_transaction(
    *,
    allocation_repository: AllocationRepository,
    trade_execution_service: TradeExecutionService,
    cognito_user_id: str,
    alpaca_account_id: str,
    allocation_id: str,
    previous_transaction_ids: set[str],
) -> str:
    deadline = monotonic() + POLL_TIMEOUT_SECONDS
    while monotonic() < deadline:
        if allocation_repository.is_exists_allocation_for_user(
            cognito_user_id=cognito_user_id,
            allocation_id=allocation_id,
        ):
            allocation = allocation_repository.get_allocation(
                cognito_user_id=cognito_user_id,
                allocation_id=allocation_id,
            )
            for transaction in reversed(allocation.transaction_history):
                if transaction.transaction_id not in previous_transaction_ids:
                    return transaction.transaction_id
            try:
                trade_execution_service.realize_filled_orders(
                    cognito_user_id=cognito_user_id,
                    alpaca_account_id=alpaca_account_id,
                    allocation_id=allocation_id,
                )
            except Exception:
                pass
        sleep(0.25)
    raise TimeoutError(f"No new transaction appeared for '{allocation_id}'.")


def _wait_for_transaction_complete(
    *,
    allocation_repository: AllocationRepository,
    trade_execution_service: TradeExecutionService,
    cognito_user_id: str,
    alpaca_account_id: str,
    allocation_id: str,
    transaction_id: str,
):
    deadline = monotonic() + POLL_TIMEOUT_SECONDS
    while monotonic() < deadline:
        allocation = allocation_repository.get_allocation(
            cognito_user_id=cognito_user_id,
            allocation_id=allocation_id,
        )
        transaction = next(
            transaction
            for transaction in allocation.transaction_history
            if transaction.transaction_id == transaction_id
        )
        if str(transaction.status).upper() in {"FULLY_FILLED", "FAILED"}:
            return allocation, transaction
        try:
            trade_execution_service.realize_filled_orders(
                cognito_user_id=cognito_user_id,
                alpaca_account_id=alpaca_account_id,
                allocation_id=allocation_id,
            )
        except Exception:
            pass
        sleep(0.25)
    raise TimeoutError(f"Transaction '{transaction_id}' did not complete.")


def _orders_for_allocation(
    *,
    order_repository: OrderRepository,
    cognito_user_id: str,
    allocation_id: str,
) -> list[dict[str, Any]]:
    try:
        return order_repository.get_orders_by_allocation(
            cognito_user_id=cognito_user_id,
            allocation_id=allocation_id,
        )
    except Exception:
        return []


def _wait_for_route_trade(
    *,
    client: TestClient,
    method: str,
    path: str,
    json: dict[str, Any] | None,
    expected_mock_action: str,
    sqs_client: Any,
    allocation_repository: AllocationRepository,
    order_repository: OrderRepository,
    trade_execution_service: TradeExecutionService,
    cognito_user_id: str,
    alpaca_account_id: str,
    allocation_id: str,
):
    previous_transaction_ids = _transaction_ids(
        allocation_repository=allocation_repository,
        cognito_user_id=cognito_user_id,
        allocation_id=allocation_id,
    )
    processed_count = (
        len(sqs_client.processed_messages)
        if _is_mock_sqs(sqs_client)
        else 0
    )

    response = client.request(method, path, json=json)
    assert response.status_code == 202
    assert response.json() == {"success": True}

    if _is_mock_sqs(sqs_client):
        sqs_client.wait_until_idle()
        assert any(
            message["message"]["action"] == expected_mock_action
            for message in sqs_client.processed_messages[processed_count:]
        )

    transaction_id = _wait_for_new_transaction(
        allocation_repository=allocation_repository,
        trade_execution_service=trade_execution_service,
        cognito_user_id=cognito_user_id,
        alpaca_account_id=alpaca_account_id,
        allocation_id=allocation_id,
        previous_transaction_ids=previous_transaction_ids,
    )
    allocation, transaction = _wait_for_transaction_complete(
        allocation_repository=allocation_repository,
        trade_execution_service=trade_execution_service,
        cognito_user_id=cognito_user_id,
        alpaca_account_id=alpaca_account_id,
        allocation_id=allocation_id,
        transaction_id=transaction_id,
    )
    assert str(transaction.status).upper() == "FULLY_FILLED"
    orders = _orders_for_allocation(
        order_repository=order_repository,
        cognito_user_id=cognito_user_id,
        allocation_id=allocation_id,
    )
    assert orders
    for order_row in orders:
        alpaca_order = trade_execution_service.alpaca_broker_client.get_order_by_id(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
            order_id=str(order_row["order_id"]),
        )
        assert str(alpaca_order.id) == str(order_row["order_id"])
        assert alpaca_order.symbol == order_row["symbol"]
    return allocation, transaction, orders


def _delete_order_rows(
    *,
    order_repository: OrderRepository,
    cognito_user_id: str,
    allocation_id: str,
) -> None:
    for order in _orders_for_allocation(
        order_repository=order_repository,
        cognito_user_id=cognito_user_id,
        allocation_id=allocation_id,
    ):
        try:
            order_repository.order_table_client.delete_item(
                key={
                    "transaction_id": str(order["transaction_id"]),
                    "order_id": str(order["order_id"]),
                }
            )
        except Exception:
            pass


def _cleanup_trade_state(
    *,
    trade_execution_service: TradeExecutionService,
    allocation_repository: AllocationRepository,
    order_repository: OrderRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    user_trade_lock_repository: UserTradeLockRepository,
    cognito_user_id: str,
    alpaca_account_id: str,
    allocation_id: str,
) -> None:
    try:
        trade_execution_service.alpaca_broker_client.execute_close_all_position(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        )
    except Exception:
        pass
    _delete_order_rows(
        order_repository=order_repository,
        cognito_user_id=cognito_user_id,
        allocation_id=allocation_id,
    )
    try:
        allocation_repository.allocation_table_client.delete_item(
            key={"cognito_user_id": cognito_user_id, "allocation_id": allocation_id}
        )
    except Exception:
        pass
    try:
        model_portfolio_follower_repository.delete_model_portfolio_follower(
            cognito_user_id=cognito_user_id,
            portfolio_id=allocation_id,
        )
    except Exception:
        pass
    try:
        user_trade_lock_repository.lock_table_client.delete_item(
            key={"cognito_user_id": cognito_user_id}
        )
    except Exception:
        pass


def _delete_model_portfolio(
    *,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    portfolio_id: str | None,
) -> None:
    if portfolio_id is None:
        return
    try:
        for access in model_portfolio_access_repository.get_accesses_for_portfolio(
            portfolio_id=portfolio_id,
            wait_for_lock=False,
        ):
            model_portfolio_access_repository.dynamodb.delete_item(
                key={
                    "portfolio_id": portfolio_id,
                    "shared_with_cognito_user_id": access.shared_with_cognito_user_id,
                }
            )
    except Exception:
        pass
    try:
        for follower in model_portfolio_follower_repository.get_model_portfolio_followers(
            portfolio_id=portfolio_id,
        ):
            model_portfolio_follower_repository.delete_model_portfolio_follower(
                cognito_user_id=follower["cognito_user_id"],
                portfolio_id=portfolio_id,
            )
    except Exception:
        pass
    try:
        model_portfolio_update_lock_repository.lock_table_client.delete_item(
            key={"portfolio_id": portfolio_id}
        )
    except Exception:
        pass
    try:
        model_portfolio_repository.dynamodb.delete_item(key={"portfolio_id": portfolio_id})
    except Exception:
        pass


@pytest.mark.parametrize(
    ("claims_factory", "expected_detail"),
    [
        (
            _claims_with_mismatched_alpaca_account,
            "Authenticated user's Alpaca account does not match Baskt account.",
        ),
        (
            _claims_with_mismatched_cognito_user_id,
            "Authenticated user does not have a Baskt account.",
        ),
    ],
)
def test_trade_execution_route_rejects_token_account_claim_mismatches(
    claims_factory: Any,
    expected_detail: str,
    trade_execution_service: TradeExecutionService,
    trade_execution_queuing_service: TradeExecutionQueuingService,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    allocation_repository: AllocationRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    asset_id = _stock_asset_id(
        trade_execution_service=trade_execution_service,
    )
    client = _client_for_claims(
        claims=claims_factory(test_user_1),
        trade_execution_queuing_service=trade_execution_queuing_service,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        allocation_repository=allocation_repository,
        baskt_account_repository=baskt_account_repository,
    )

    response = client.post(
        f"/trade-execution/stocks/{asset_id}/buy",
        json={"amount": 100.0},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == expected_detail


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/trade-execution/portfolios/portfolio-1/deposit", {}),
        ("/trade-execution/portfolios/portfolio-1/withdrawal", {}),
        ("/trade-execution/stocks/asset-1/buy", {}),
        ("/trade-execution/stocks/asset-1/sell", {}),
        ("/trade-execution/portfolios/portfolio-1/deposit", {"amount": 0}),
        ("/trade-execution/portfolios/portfolio-1/withdrawal", {"amount": -1}),
        ("/trade-execution/stocks/asset-1/buy", {"amount": 0}),
        ("/trade-execution/stocks/asset-1/sell", {"amount": -1}),
    ],
)
def test_trade_execution_route_rejects_schema_invalid_requests(
    path: str,
    payload: dict[str, Any],
    account_lifecycle_service: AccountLifecycleService,
    trade_execution_service: TradeExecutionService,
    trade_execution_queuing_service: TradeExecutionQueuingService,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    allocation_repository: AllocationRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    baskt_account = _baskt_account(
        account_lifecycle_service=account_lifecycle_service,
        test_user=test_user_1,
    )
    client = _client_for_user(
        test_user=test_user_1,
        baskt_account=baskt_account,
        alpaca_account=_alpaca_account(
            account_lifecycle_service=account_lifecycle_service,
            trade_execution_service=trade_execution_service,
            test_user=test_user_1,
        ),
        trade_execution_queuing_service=trade_execution_queuing_service,
        model_portfolio_repository=model_portfolio_repository,
        model_portfolio_access_repository=model_portfolio_access_repository,
        allocation_repository=allocation_repository,
        baskt_account_repository=baskt_account_repository,
    )

    response = client.post(path, json=payload)

    assert response.status_code == 422


def test_trade_execution_route_maps_queue_amount_validation_to_422(
    account_lifecycle_service: AccountLifecycleService,
    trade_execution_service: TradeExecutionService,
    trade_execution_queuing_service: TradeExecutionQueuingService,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    allocation_repository: AllocationRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    portfolio_id: str | None = None
    try:
        portfolio_id = _create_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=test_user_1.cognito_user_id,
            visibility="PUBLIC",
        )
        baskt_account = _baskt_account(
            account_lifecycle_service=account_lifecycle_service,
            test_user=test_user_1,
        )
        client = _client_for_user(
            test_user=test_user_1,
            baskt_account=baskt_account,
            alpaca_account=_alpaca_account(
                account_lifecycle_service=account_lifecycle_service,
                trade_execution_service=trade_execution_service,
                test_user=test_user_1,
            ),
            trade_execution_queuing_service=trade_execution_queuing_service,
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            allocation_repository=allocation_repository,
            baskt_account_repository=baskt_account_repository,
        )

        response = client.post(
            f"/trade-execution/portfolios/{portfolio_id}/deposit",
            json={"amount": 5.0},
        )

        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "TRADE_EXECUTION_QUEUE_AMOUNT_INVALID"
    finally:
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            model_portfolio_follower_repository=model_portfolio_follower_repository,
            model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id,
        )


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("POST", "/trade-execution/portfolios/{portfolio_id}/deposit", {"amount": 100.0}),
        ("POST", "/trade-execution/portfolios/{portfolio_id}/withdrawal", {"amount": 20.0}),
        ("POST", "/trade-execution/portfolios/{portfolio_id}/withdraw-all", None),
        ("POST", "/trade-execution/stocks/{asset_id}/buy", {"amount": 100.0}),
        ("POST", "/trade-execution/stocks/{asset_id}/sell", {"amount": 20.0}),
        ("POST", "/trade-execution/stocks/{asset_id}/close", None),
    ],
)
def test_trade_execution_route_rejects_inactive_alpaca_account(
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    account_lifecycle_service: AccountLifecycleService,
    trade_execution_service: TradeExecutionService,
    trade_execution_queuing_service: TradeExecutionQueuingService,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    allocation_repository: AllocationRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    portfolio_id: str | None = None
    try:
        portfolio_id = _create_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=test_user_1.cognito_user_id,
            visibility="PUBLIC",
        )
        asset_id = _stock_asset_id(
            trade_execution_service=trade_execution_service,
        )
        baskt_account = _baskt_account(
            account_lifecycle_service=account_lifecycle_service,
            test_user=test_user_1,
        )
        client = _client_for_user(
            test_user=test_user_1,
            baskt_account=baskt_account,
            alpaca_account=_inactive_alpaca_account(test_user_1),
            trade_execution_queuing_service=trade_execution_queuing_service,
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            allocation_repository=allocation_repository,
            baskt_account_repository=baskt_account_repository,
        )

        response = client.request(
            method,
            path.format(portfolio_id=portfolio_id, asset_id=asset_id),
            json=payload,
        )

        assert response.status_code == 403
    finally:
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            model_portfolio_follower_repository=model_portfolio_follower_repository,
            model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id,
        )


def test_trade_execution_route_denies_private_portfolio_without_access(
    account_lifecycle_service: AccountLifecycleService,
    trade_execution_service: TradeExecutionService,
    trade_execution_queuing_service: TradeExecutionQueuingService,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    allocation_repository: AllocationRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    portfolio_id: str | None = None
    try:
        portfolio_id = _create_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=test_user_1.cognito_user_id,
            visibility="PRIVATE",
        )
        baskt_account = _baskt_account(
            account_lifecycle_service=account_lifecycle_service,
            test_user=test_user_2,
        )
        client = _client_for_user(
            test_user=test_user_2,
            baskt_account=baskt_account,
            alpaca_account=_alpaca_account(
                account_lifecycle_service=account_lifecycle_service,
                trade_execution_service=trade_execution_service,
                test_user=test_user_2,
            ),
            trade_execution_queuing_service=trade_execution_queuing_service,
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            allocation_repository=allocation_repository,
            baskt_account_repository=baskt_account_repository,
        )

        for path, payload in [
            (f"/trade-execution/portfolios/{portfolio_id}/deposit", {"amount": 100.0}),
            (f"/trade-execution/portfolios/{portfolio_id}/withdrawal", {"amount": 20.0}),
            (f"/trade-execution/portfolios/{portfolio_id}/withdraw-all", None),
        ]:
            response = client.post(path, json=payload)
            assert response.status_code == 403
    finally:
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            model_portfolio_follower_repository=model_portfolio_follower_repository,
            model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id,
        )


def test_trade_execution_portfolio_owner_deposit_withdraw_and_withdraw_all_workflow(
    account_lifecycle_service: AccountLifecycleService,
    trade_execution_service: TradeExecutionService,
    trade_execution_queuing_service: TradeExecutionQueuingService,
    sqs_client: Any,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    allocation_repository: AllocationRepository,
    order_repository: OrderRepository,
    user_trade_lock_repository: UserTradeLockRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    portfolio_id: str | None = None
    try:
        portfolio_id = _create_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=test_user_1.cognito_user_id,
            visibility="PUBLIC",
        )
        baskt_account = _baskt_account(
            account_lifecycle_service=account_lifecycle_service,
            test_user=test_user_1,
        )
        client = _client_for_user(
            test_user=test_user_1,
            baskt_account=baskt_account,
            alpaca_account=_alpaca_account(
                account_lifecycle_service=account_lifecycle_service,
                trade_execution_service=trade_execution_service,
                test_user=test_user_1,
            ),
            trade_execution_queuing_service=trade_execution_queuing_service,
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            allocation_repository=allocation_repository,
            baskt_account_repository=baskt_account_repository,
        )

        deposit_allocation, _, _ = _wait_for_route_trade(
            client=client,
            method="POST",
            path=f"/trade-execution/portfolios/{portfolio_id}/deposit",
            json={"amount": 150.0},
            expected_mock_action="portfolio_deposit",
            sqs_client=sqs_client,
            allocation_repository=allocation_repository,
            order_repository=order_repository,
            trade_execution_service=trade_execution_service,
            cognito_user_id=test_user_1.cognito_user_id,
            alpaca_account_id=test_user_1.alpaca_account_id,
            allocation_id=portfolio_id,
        )
        assert deposit_allocation.open_positions is True

        partial_allocation, _, _ = _wait_for_route_trade(
            client=client,
            method="POST",
            path=f"/trade-execution/portfolios/{portfolio_id}/withdrawal",
            json={"amount": 25.0},
            expected_mock_action="portfolio_withdraw",
            sqs_client=sqs_client,
            allocation_repository=allocation_repository,
            order_repository=order_repository,
            trade_execution_service=trade_execution_service,
            cognito_user_id=test_user_1.cognito_user_id,
            alpaca_account_id=test_user_1.alpaca_account_id,
            allocation_id=portfolio_id,
        )
        assert partial_allocation.open_positions is True

        final_allocation, _, _ = _wait_for_route_trade(
            client=client,
            method="POST",
            path=f"/trade-execution/portfolios/{portfolio_id}/withdraw-all",
            json=None,
            expected_mock_action="portfolio_withdraw_all",
            sqs_client=sqs_client,
            allocation_repository=allocation_repository,
            order_repository=order_repository,
            trade_execution_service=trade_execution_service,
            cognito_user_id=test_user_1.cognito_user_id,
            alpaca_account_id=test_user_1.alpaca_account_id,
            allocation_id=portfolio_id,
        )
        assert final_allocation.open_positions is False
    finally:
        if portfolio_id is not None:
            _cleanup_trade_state(
                trade_execution_service=trade_execution_service,
                allocation_repository=allocation_repository,
                order_repository=order_repository,
                model_portfolio_follower_repository=model_portfolio_follower_repository,
                user_trade_lock_repository=user_trade_lock_repository,
                cognito_user_id=test_user_1.cognito_user_id,
                alpaca_account_id=test_user_1.alpaca_account_id,
                allocation_id=portfolio_id,
            )
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            model_portfolio_follower_repository=model_portfolio_follower_repository,
            model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id,
        )


def test_trade_execution_stock_buy_sell_and_close_workflow(
    account_lifecycle_service: AccountLifecycleService,
    trade_execution_service: TradeExecutionService,
    trade_execution_queuing_service: TradeExecutionQueuingService,
    sqs_client: Any,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    allocation_repository: AllocationRepository,
    order_repository: OrderRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    user_trade_lock_repository: UserTradeLockRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    asset_id = _stock_asset_id(
        trade_execution_service=trade_execution_service,
    )
    try:
        baskt_account = _baskt_account(
            account_lifecycle_service=account_lifecycle_service,
            test_user=test_user_1,
        )
        client = _client_for_user(
            test_user=test_user_1,
            baskt_account=baskt_account,
            alpaca_account=_alpaca_account(
                account_lifecycle_service=account_lifecycle_service,
                trade_execution_service=trade_execution_service,
                test_user=test_user_1,
            ),
            trade_execution_queuing_service=trade_execution_queuing_service,
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            allocation_repository=allocation_repository,
            baskt_account_repository=baskt_account_repository,
        )

        buy_allocation, _, _ = _wait_for_route_trade(
            client=client,
            method="POST",
            path=f"/trade-execution/stocks/{asset_id}/buy",
            json={"amount": 150.0},
            expected_mock_action="stock_buy",
            sqs_client=sqs_client,
            allocation_repository=allocation_repository,
            order_repository=order_repository,
            trade_execution_service=trade_execution_service,
            cognito_user_id=test_user_1.cognito_user_id,
            alpaca_account_id=test_user_1.alpaca_account_id,
            allocation_id=asset_id,
        )
        assert buy_allocation.open_positions is True

        sell_allocation, _, _ = _wait_for_route_trade(
            client=client,
            method="POST",
            path=f"/trade-execution/stocks/{asset_id}/sell",
            json={"amount": 25.0},
            expected_mock_action="stock_sell",
            sqs_client=sqs_client,
            allocation_repository=allocation_repository,
            order_repository=order_repository,
            trade_execution_service=trade_execution_service,
            cognito_user_id=test_user_1.cognito_user_id,
            alpaca_account_id=test_user_1.alpaca_account_id,
            allocation_id=asset_id,
        )
        assert sell_allocation.open_positions is True

        close_allocation, _, _ = _wait_for_route_trade(
            client=client,
            method="POST",
            path=f"/trade-execution/stocks/{asset_id}/close",
            json=None,
            expected_mock_action="stock_close",
            sqs_client=sqs_client,
            allocation_repository=allocation_repository,
            order_repository=order_repository,
            trade_execution_service=trade_execution_service,
            cognito_user_id=test_user_1.cognito_user_id,
            alpaca_account_id=test_user_1.alpaca_account_id,
            allocation_id=asset_id,
        )
        assert close_allocation.open_positions is False
    finally:
        _cleanup_trade_state(
            trade_execution_service=trade_execution_service,
            allocation_repository=allocation_repository,
            order_repository=order_repository,
            model_portfolio_follower_repository=model_portfolio_follower_repository,
            user_trade_lock_repository=user_trade_lock_repository,
            cognito_user_id=test_user_1.cognito_user_id,
            alpaca_account_id=test_user_1.alpaca_account_id,
            allocation_id=asset_id,
        )


def test_trade_execution_route_user_trade_lock_maps_to_409(
    account_lifecycle_service: AccountLifecycleService,
    trade_execution_service: TradeExecutionService,
    trade_execution_queuing_service: TradeExecutionQueuingService,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    allocation_repository: AllocationRepository,
    user_trade_lock_repository: UserTradeLockRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
) -> None:
    portfolio_id: str | None = None
    owner_token = str(uuid4())
    try:
        portfolio_id = _create_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=test_user_1.cognito_user_id,
            visibility="PUBLIC",
        )
        assert user_trade_lock_repository.acquire_lock(
            cognito_user_id=test_user_1.cognito_user_id,
            owner_token=owner_token,
            lease_seconds=120,
        )
        baskt_account = _baskt_account(
            account_lifecycle_service=account_lifecycle_service,
            test_user=test_user_1,
        )
        client = _client_for_user(
            test_user=test_user_1,
            baskt_account=baskt_account,
            alpaca_account=_alpaca_account(
                account_lifecycle_service=account_lifecycle_service,
                trade_execution_service=trade_execution_service,
                test_user=test_user_1,
            ),
            trade_execution_queuing_service=trade_execution_queuing_service,
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            allocation_repository=allocation_repository,
            baskt_account_repository=baskt_account_repository,
        )

        response = client.post(
            f"/trade-execution/portfolios/{portfolio_id}/deposit",
            json={"amount": 100.0},
        )

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "TRADE_EXECUTION_QUEUE_LOCKED"
    finally:
        try:
            user_trade_lock_repository.release_lock(
                cognito_user_id=test_user_1.cognito_user_id,
                owner_token=owner_token,
            )
        except Exception:
            pass
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            model_portfolio_follower_repository=model_portfolio_follower_repository,
            model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id,
        )


def test_trade_execution_public_non_owner_partial_withdraw_keeps_follower(
    account_lifecycle_service: AccountLifecycleService,
    trade_execution_service: TradeExecutionService,
    trade_execution_queuing_service: TradeExecutionQueuingService,
    sqs_client: Any,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    allocation_repository: AllocationRepository,
    order_repository: OrderRepository,
    user_trade_lock_repository: UserTradeLockRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    owner_user = test_user_2
    trader_user = test_user_1
    portfolio_id: str | None = None
    try:
        portfolio_id = _create_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=owner_user.cognito_user_id,
            visibility="PUBLIC",
        )
        baskt_account = _baskt_account(
            account_lifecycle_service=account_lifecycle_service,
            test_user=trader_user,
        )
        client = _client_for_user(
            test_user=trader_user,
            baskt_account=baskt_account,
            alpaca_account=_alpaca_account(
                account_lifecycle_service=account_lifecycle_service,
                trade_execution_service=trade_execution_service,
                test_user=trader_user,
            ),
            trade_execution_queuing_service=trade_execution_queuing_service,
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            allocation_repository=allocation_repository,
            baskt_account_repository=baskt_account_repository,
        )

        _wait_for_route_trade(
            client=client,
            method="POST",
            path=f"/trade-execution/portfolios/{portfolio_id}/deposit",
            json={"amount": 150.0},
            expected_mock_action="portfolio_deposit",
            sqs_client=sqs_client,
            allocation_repository=allocation_repository,
            order_repository=order_repository,
            trade_execution_service=trade_execution_service,
            cognito_user_id=trader_user.cognito_user_id,
            alpaca_account_id=trader_user.alpaca_account_id,
            allocation_id=portfolio_id,
        )
        assert model_portfolio_follower_repository.is_model_portfolio_follower(
            cognito_user_id=trader_user.cognito_user_id,
            portfolio_id=portfolio_id,
        )
        access_record = model_portfolio_access_repository.get_access_record(
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=trader_user.cognito_user_id,
        )
        assert access_record is not None
        assert access_record.granted_access_by == "ALLOCATION"
        assert access_record.status == "ACTIVE"

        partial_allocation, _, _ = _wait_for_route_trade(
            client=client,
            method="POST",
            path=f"/trade-execution/portfolios/{portfolio_id}/withdrawal",
            json={"amount": 25.0},
            expected_mock_action="portfolio_withdraw",
            sqs_client=sqs_client,
            allocation_repository=allocation_repository,
            order_repository=order_repository,
            trade_execution_service=trade_execution_service,
            cognito_user_id=trader_user.cognito_user_id,
            alpaca_account_id=trader_user.alpaca_account_id,
            allocation_id=portfolio_id,
        )

        assert partial_allocation.open_positions is True
        assert model_portfolio_follower_repository.is_model_portfolio_follower(
            cognito_user_id=trader_user.cognito_user_id,
            portfolio_id=portfolio_id,
        )
        access_record = model_portfolio_access_repository.get_access_record(
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=trader_user.cognito_user_id,
        )
        assert access_record is not None
        assert access_record.granted_access_by == "ALLOCATION"
        assert access_record.status == "ACTIVE"
    finally:
        if portfolio_id is not None:
            _cleanup_trade_state(
                trade_execution_service=trade_execution_service,
                allocation_repository=allocation_repository,
                order_repository=order_repository,
                model_portfolio_follower_repository=model_portfolio_follower_repository,
                user_trade_lock_repository=user_trade_lock_repository,
                cognito_user_id=trader_user.cognito_user_id,
                alpaca_account_id=trader_user.alpaca_account_id,
                allocation_id=portfolio_id,
            )
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            model_portfolio_follower_repository=model_portfolio_follower_repository,
            model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id,
        )


def test_trade_execution_public_deposit_then_private_partial_withdraw_keeps_follower(
    account_lifecycle_service: AccountLifecycleService,
    trade_execution_service: TradeExecutionService,
    trade_execution_queuing_service: TradeExecutionQueuingService,
    sqs_client: Any,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    allocation_repository: AllocationRepository,
    order_repository: OrderRepository,
    user_trade_lock_repository: UserTradeLockRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    owner_user = test_user_2
    trader_user = test_user_1
    portfolio_id: str | None = None
    try:
        portfolio_id = _create_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=owner_user.cognito_user_id,
            visibility="PUBLIC",
        )
        baskt_account = _baskt_account(
            account_lifecycle_service=account_lifecycle_service,
            test_user=trader_user,
        )
        client = _client_for_user(
            test_user=trader_user,
            baskt_account=baskt_account,
            alpaca_account=_alpaca_account(
                account_lifecycle_service=account_lifecycle_service,
                trade_execution_service=trade_execution_service,
                test_user=trader_user,
            ),
            trade_execution_queuing_service=trade_execution_queuing_service,
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            allocation_repository=allocation_repository,
            baskt_account_repository=baskt_account_repository,
        )

        _wait_for_route_trade(
            client=client,
            method="POST",
            path=f"/trade-execution/portfolios/{portfolio_id}/deposit",
            json={"amount": 150.0},
            expected_mock_action="portfolio_deposit",
            sqs_client=sqs_client,
            allocation_repository=allocation_repository,
            order_repository=order_repository,
            trade_execution_service=trade_execution_service,
            cognito_user_id=trader_user.cognito_user_id,
            alpaca_account_id=trader_user.alpaca_account_id,
            allocation_id=portfolio_id,
        )
        assert model_portfolio_follower_repository.is_model_portfolio_follower(
            cognito_user_id=trader_user.cognito_user_id,
            portfolio_id=portfolio_id,
        )
        access_record = model_portfolio_access_repository.get_access_record(
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=trader_user.cognito_user_id,
        )
        assert access_record is not None
        assert access_record.granted_access_by == "ALLOCATION"
        assert access_record.status == "ACTIVE"

        _make_private(
            model_portfolio_repository=model_portfolio_repository,
            portfolio_id=portfolio_id,
        )
        access_record = model_portfolio_access_repository.get_access_record(
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=trader_user.cognito_user_id,
        )
        assert access_record is not None
        assert access_record.granted_access_by == "ALLOCATION"
        assert access_record.status == "TO_BE_DELETED"

        allocation, _, _ = _wait_for_route_trade(
            client=client,
            method="POST",
            path=f"/trade-execution/portfolios/{portfolio_id}/withdrawal",
            json={"amount": 25.0},
            expected_mock_action="portfolio_withdraw",
            sqs_client=sqs_client,
            allocation_repository=allocation_repository,
            order_repository=order_repository,
            trade_execution_service=trade_execution_service,
            cognito_user_id=trader_user.cognito_user_id,
            alpaca_account_id=trader_user.alpaca_account_id,
            allocation_id=portfolio_id,
        )

        assert allocation.open_positions is True
        assert model_portfolio_follower_repository.is_model_portfolio_follower(
            cognito_user_id=trader_user.cognito_user_id,
            portfolio_id=portfolio_id,
        )
        access_record = model_portfolio_access_repository.get_access_record(
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=trader_user.cognito_user_id,
        )
        assert access_record is not None
        assert access_record.granted_access_by == "ALLOCATION"
        assert access_record.status == "TO_BE_DELETED"
    finally:
        if portfolio_id is not None:
            _cleanup_trade_state(
                trade_execution_service=trade_execution_service,
                allocation_repository=allocation_repository,
                order_repository=order_repository,
                model_portfolio_follower_repository=model_portfolio_follower_repository,
                user_trade_lock_repository=user_trade_lock_repository,
                cognito_user_id=trader_user.cognito_user_id,
                alpaca_account_id=trader_user.alpaca_account_id,
                allocation_id=portfolio_id,
            )
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            model_portfolio_follower_repository=model_portfolio_follower_repository,
            model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id,
        )


@pytest.mark.parametrize("visibility", ["PUBLIC", "PRIVATE"])
def test_trade_execution_non_owner_withdraw_all_removes_follower(
    visibility: str,
    account_lifecycle_service: AccountLifecycleService,
    trade_execution_service: TradeExecutionService,
    trade_execution_queuing_service: TradeExecutionQueuingService,
    sqs_client: Any,
    model_portfolio_repository: ModelPortfolioRepository,
    model_portfolio_access_repository: ModelPortfolioAccessRepository,
    model_portfolio_follower_repository: ModelPortfolioFollowerRepository,
    model_portfolio_update_lock_repository: ModelPortfolioUpdateLockRepository,
    allocation_repository: AllocationRepository,
    order_repository: OrderRepository,
    user_trade_lock_repository: UserTradeLockRepository,
    baskt_account_repository: BasktAccountRepository,
    test_user_1: Any,
    test_user_2: Any,
) -> None:
    owner_user = test_user_2
    trader_user = test_user_1
    portfolio_id: str | None = None
    try:
        portfolio_id = _create_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=owner_user.cognito_user_id,
            visibility=visibility,
        )
        if visibility == "PRIVATE":
            model_portfolio_access_repository.add_access_via_email(
                portfolio_id=portfolio_id,
                portfolio_owner_cognito_user_id=owner_user.cognito_user_id,
                shared_with_email=trader_user.email_address,
                granted_access_by="PORTFOLIO_OWNER",
            )
        baskt_account = _baskt_account(
            account_lifecycle_service=account_lifecycle_service,
            test_user=trader_user,
        )
        client = _client_for_user(
            test_user=trader_user,
            baskt_account=baskt_account,
            alpaca_account=_alpaca_account(
                account_lifecycle_service=account_lifecycle_service,
                trade_execution_service=trade_execution_service,
                test_user=trader_user,
            ),
            trade_execution_queuing_service=trade_execution_queuing_service,
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            allocation_repository=allocation_repository,
            baskt_account_repository=baskt_account_repository,
        )

        _wait_for_route_trade(
            client=client,
            method="POST",
            path=f"/trade-execution/portfolios/{portfolio_id}/deposit",
            json={"amount": 150.0},
            expected_mock_action="portfolio_deposit",
            sqs_client=sqs_client,
            allocation_repository=allocation_repository,
            order_repository=order_repository,
            trade_execution_service=trade_execution_service,
            cognito_user_id=trader_user.cognito_user_id,
            alpaca_account_id=trader_user.alpaca_account_id,
            allocation_id=portfolio_id,
        )
        assert model_portfolio_follower_repository.is_model_portfolio_follower(
            cognito_user_id=trader_user.cognito_user_id,
            portfolio_id=portfolio_id,
        )
        access_record = model_portfolio_access_repository.get_access_record(
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=trader_user.cognito_user_id,
        )
        assert access_record is not None
        if visibility == "PRIVATE":
            assert access_record.granted_access_by == "PORTFOLIO_OWNER"
            assert access_record.status == "ACTIVE"
        else:
            assert access_record.granted_access_by == "ALLOCATION"
            assert access_record.status == "ACTIVE"

        allocation, _, _ = _wait_for_route_trade(
            client=client,
            method="POST",
            path=f"/trade-execution/portfolios/{portfolio_id}/withdraw-all",
            json=None,
            expected_mock_action="portfolio_withdraw_all",
            sqs_client=sqs_client,
            allocation_repository=allocation_repository,
            order_repository=order_repository,
            trade_execution_service=trade_execution_service,
            cognito_user_id=trader_user.cognito_user_id,
            alpaca_account_id=trader_user.alpaca_account_id,
            allocation_id=portfolio_id,
        )

        assert allocation.open_positions is False
        assert not model_portfolio_follower_repository.is_model_portfolio_follower(
            cognito_user_id=trader_user.cognito_user_id,
            portfolio_id=portfolio_id,
        )
        if visibility == "PRIVATE":
            access_record = model_portfolio_access_repository.get_access_record(
                portfolio_id=portfolio_id,
                shared_with_cognito_user_id=trader_user.cognito_user_id,
            )
            assert access_record is not None
            assert access_record.granted_access_by == "PORTFOLIO_OWNER"
            assert access_record.status == "ACTIVE"
        else:
            assert not model_portfolio_access_repository.has_access(
                portfolio_id=portfolio_id,
                shared_with_cognito_user_id=trader_user.cognito_user_id,
            )
    finally:
        if portfolio_id is not None:
            _cleanup_trade_state(
                trade_execution_service=trade_execution_service,
                allocation_repository=allocation_repository,
                order_repository=order_repository,
                model_portfolio_follower_repository=model_portfolio_follower_repository,
                user_trade_lock_repository=user_trade_lock_repository,
                cognito_user_id=trader_user.cognito_user_id,
                alpaca_account_id=trader_user.alpaca_account_id,
                allocation_id=portfolio_id,
            )
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            model_portfolio_access_repository=model_portfolio_access_repository,
            model_portfolio_follower_repository=model_portfolio_follower_repository,
            model_portfolio_update_lock_repository=model_portfolio_update_lock_repository,
            portfolio_id=portfolio_id,
        )
