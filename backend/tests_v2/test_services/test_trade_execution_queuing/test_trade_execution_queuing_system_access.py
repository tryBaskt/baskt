from time import sleep
from datetime import timedelta
import uuid

import pytest

from alpaca.trading.models import Order
from botocore.exceptions import ClientError

from schema.model_portfolio_schema import ModelPortfolioPositionRequest
from services.trade_execution_queuing_service import (
    TradeExecutionQueuingInternalServerError,
)

from .conftest import TestEngine


"""
These integrated trade-execution queuing tests focus on model portfolio access
records that are created, preserved, status-transitioned, or deleted by deposit
and withdraw flows.

Coverage goals:
- Public non-owner deposits create one ALLOCATION/ACTIVE access record and a
  follower record.
- Owner deposits do not create a self-access record.
- Public deposits do not downgrade an existing PORTFOLIO_OWNER grant.
- Queue-send failure after a newly created ALLOCATION access record rolls that
  access record back and does not create a follower record.
- Public-to-private visibility changes move existing ALLOCATION access records
  to TO_BE_DELETED while preserving followers.
- Private-to-public visibility changes restore TO_BE_DELETED ALLOCATION access
  records to ACTIVE.
- Partial withdrawals keep follower records and preserve the current allocation
  access status.
- Withdraw-all removes followers and allocation-only access records.
- Withdraw-all after public-to-private removes pending allocation access records.
- Withdraw-all from an owner-granted private portfolio preserves
  PORTFOLIO_OWNER/ACTIVE access.
- Owner grants upgrade allocation access, survive withdraw-all, and second
  deposits do not create duplicate access records.
"""


@pytest.fixture(autouse=True)
def pause_between_test_cases():
    yield
    sleep(5)


def _create_portfolio(
    test_engine: TestEngine,
    *,
    portfolio_owner_cognito_user_id: str,
    portfolio_name_prefix: str,
) -> str:
    return test_engine.test_create_portfolio(
        symbols=["AAPL", "MSFT"],
        directions=[1, 1],
        target_weights=[0.6, 0.4],
        leverages=[1.0, 1.0],
        portfolio_name=f"{portfolio_name_prefix}-{uuid.uuid4()}",
        portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
    )


def _position_requests(test_engine: TestEngine, portfolio_id: str):
    model_portfolio = test_engine.model_portfolio_repository.get_model_portfolio(
        portfolio_id=portfolio_id
    )
    return [
        ModelPortfolioPositionRequest(
            symbol=position.symbol,
            target_weight=position.target_weight,
            direction=position.direction,
            leverage=position.leverage,
        )
        for position in model_portfolio.position_history[-1].positions
    ]


def _set_visibility(test_engine: TestEngine, *, portfolio_id: str, visibility: str) -> None:
    update_time = test_engine.model_portfolio_update_times[portfolio_id][-1] + timedelta(
        minutes=2
    )
    updated, snapshot_id = test_engine.model_portfolio_repository.update_model_portfolio(
        portfolio_id=portfolio_id,
        positions_request=_position_requests(test_engine, portfolio_id),
        visibility=visibility,
        update_time=update_time,
    )
    assert updated is True
    assert snapshot_id is None
    test_engine.model_portfolio_update_times[portfolio_id].append(update_time)


def _deposit(
    test_engine: TestEngine,
    *,
    portfolio_id: str,
    cognito_user_id: str,
    alpaca_account_id: str,
    portfolio_owner_cognito_user_id: str,
    amount: float = 150.0,
):
    return test_engine.test_deposit(
        deposit_amount=amount,
        portfolio_id=portfolio_id,
        cognito_user_id=cognito_user_id,
        alpaca_account_id=alpaca_account_id,
        portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
    )


def _withdraw(
    test_engine: TestEngine,
    *,
    portfolio_id: str,
    cognito_user_id: str,
    alpaca_account_id: str,
    portfolio_owner_cognito_user_id: str,
    amount: float = 25.0,
):
    return test_engine.test_withdraw(
        portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
        cognito_user_id=cognito_user_id,
        alpaca_account_id=alpaca_account_id,
        portfolio_id=portfolio_id,
        withdraw_amount=amount,
    )


def _withdraw_all(
    test_engine: TestEngine,
    *,
    portfolio_id: str,
    cognito_user_id: str,
    alpaca_account_id: str,
    portfolio_owner_cognito_user_id: str,
):
    return test_engine.test_withdraw_all(
        portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
        alpaca_account_id=alpaca_account_id,
        cognito_user_id=cognito_user_id,
        portfolio_id=portfolio_id,
    )


def _cleanup(
    test_engine: TestEngine,
    *,
    portfolio_id: str | None,
    transaction_id_order_id_dict: dict[str, list[Order]],
    traded_accounts: list[list[str]] | None = None,
    portfolio_owner_cognito_user_id: str | None = None,
) -> None:
    if portfolio_id is None:
        return
    test_engine.test_clean_up(
        traded_accounts=traded_accounts or [],
        portfolio_owner_model_portfolios=[
            [
                portfolio_owner_cognito_user_id
                or test_engine.portfolio_owner_cognito_user_id,
                portfolio_id,
            ]
        ],
        transaction_id_order_id_dict=transaction_id_order_id_dict,
    )


def _record_response(
    transaction_id_order_id_dict: dict[str, list[Order]],
    response,
) -> None:
    transaction_id_order_id_dict[response["transaction_id"]] = response["orders"]


def _assert_access(
    test_engine: TestEngine,
    *,
    portfolio_id: str,
    cognito_user_id: str,
    granted_access_by: str,
    status: str,
) -> None:
    access_record = test_engine.model_portfolio_access_repository.get_access_record(
        portfolio_id=portfolio_id,
        shared_with_cognito_user_id=cognito_user_id,
    )
    assert access_record is not None
    assert access_record.granted_access_by == granted_access_by
    assert access_record.status == status


def _assert_no_access(
    test_engine: TestEngine,
    *,
    portfolio_id: str,
    cognito_user_id: str,
) -> None:
    assert (
        test_engine.model_portfolio_access_repository.get_access_record(
            portfolio_id=portfolio_id,
            shared_with_cognito_user_id=cognito_user_id,
        )
        is None
    )


def _assert_follower(
    test_engine: TestEngine,
    *,
    portfolio_id: str,
    cognito_user_id: str,
    expected: bool,
) -> None:
    assert (
        test_engine.model_portfolio_follower_repository.is_model_portfolio_follower(
            cognito_user_id=cognito_user_id,
            portfolio_id=portfolio_id,
        )
        is expected
    )


def _access_count(
    test_engine: TestEngine,
    *,
    portfolio_id: str,
    cognito_user_id: str,
) -> int:
    return sum(
        1
        for access_record in (
            test_engine.model_portfolio_access_repository.get_accesses_for_portfolio(
                portfolio_id=portfolio_id
            )
        )
        if access_record.shared_with_cognito_user_id == cognito_user_id
    )


def _grant_owner_access(
    test_engine: TestEngine,
    *,
    portfolio_id: str,
    cognito_user_id: str,
) -> None:
    test_engine.model_portfolio_access_repository.add_access_via_cognito_user_id(
        portfolio_id=portfolio_id,
        portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
        shared_with_cognito_user_id=cognito_user_id,
        granted_access_by="PORTFOLIO_OWNER",
    )


@pytest.mark.integration
def test_public_non_owner_deposit_creates_allocation_access(test_engine: TestEngine):
    portfolio_id = None
    transaction_id_order_id_dict: dict[str, list[Order]] = {}
    try:
        portfolio_id = _create_portfolio(
            test_engine,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
            portfolio_name_prefix="access-public-deposit",
        )
        response = _deposit(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
        )
        _record_response(transaction_id_order_id_dict, response)

        _assert_follower(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            expected=True,
        )
        _assert_access(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            granted_access_by="ALLOCATION",
            status="ACTIVE",
        )
    finally:
        _cleanup(
            test_engine,
            portfolio_id=portfolio_id,
            transaction_id_order_id_dict=transaction_id_order_id_dict,
            traded_accounts=[
                [
                    test_engine.funded_50000_cognito_user_id,
                    test_engine.funded_50000_alpaca_account_id,
                    portfolio_id,
                ]
            ],
        )


@pytest.mark.integration
def test_owner_deposit_does_not_create_self_access_record(test_engine: TestEngine):
    portfolio_id = None
    transaction_id_order_id_dict: dict[str, list[Order]] = {}
    try:
        portfolio_id = _create_portfolio(
            test_engine,
            portfolio_owner_cognito_user_id=test_engine.funded_50000_cognito_user_id,
            portfolio_name_prefix="access-owner-deposit",
        )
        response = _deposit(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            portfolio_owner_cognito_user_id=test_engine.funded_50000_cognito_user_id,
            amount=50.0,
        )
        _record_response(transaction_id_order_id_dict, response)

        _assert_no_access(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
        )
    finally:
        _cleanup(
            test_engine,
            portfolio_id=portfolio_id,
            transaction_id_order_id_dict=transaction_id_order_id_dict,
            traded_accounts=[
                [
                    test_engine.funded_50000_cognito_user_id,
                    test_engine.funded_50000_alpaca_account_id,
                    portfolio_id,
                ]
            ],
            portfolio_owner_cognito_user_id=test_engine.funded_50000_cognito_user_id,
        )


@pytest.mark.integration
def test_public_deposit_does_not_downgrade_owner_granted_access(
    test_engine: TestEngine,
):
    portfolio_id = None
    transaction_id_order_id_dict: dict[str, list[Order]] = {}
    try:
        portfolio_id = _create_portfolio(
            test_engine,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
            portfolio_name_prefix="access-owner-grant-public-deposit",
        )
        _grant_owner_access(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
        )
        response = _deposit(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
        )
        _record_response(transaction_id_order_id_dict, response)

        _assert_access(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            granted_access_by="PORTFOLIO_OWNER",
            status="ACTIVE",
        )
    finally:
        _cleanup(
            test_engine,
            portfolio_id=portfolio_id,
            transaction_id_order_id_dict=transaction_id_order_id_dict,
            traded_accounts=[
                [
                    test_engine.funded_50000_cognito_user_id,
                    test_engine.funded_50000_alpaca_account_id,
                    portfolio_id,
                ]
            ],
        )


@pytest.mark.integration
def test_queue_send_failure_rolls_back_new_allocation_access(
    test_engine: TestEngine,
    monkeypatch: pytest.MonkeyPatch,
):
    portfolio_id = None
    try:
        portfolio_id = _create_portfolio(
            test_engine,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
            portfolio_name_prefix="access-queue-failure",
        )

        def fail_send_message(*, QueueUrl, MessageBody):
            raise ClientError(
                error_response={
                    "Error": {
                        "Code": "InternalError",
                        "Message": "forced queue failure",
                    }
                },
                operation_name="SendMessage",
            )

        monkeypatch.setattr(test_engine.sqs_client, "send_message", fail_send_message)

        with pytest.raises(TradeExecutionQueuingInternalServerError) as exc_info:
            test_engine.trade_execution_queuing_service.queue_portfolio_deposit(
                portfolio_id=portfolio_id,
                amount=150.0,
                cognito_user_id=test_engine.funded_50000_cognito_user_id,
                alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            )

        assert exc_info.value.code == "TRADE_EXECUTION_QUEUE_SEND_FAILED"
        _assert_no_access(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
        )
        _assert_follower(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            expected=False,
        )
    finally:
        _cleanup(
            test_engine,
            portfolio_id=portfolio_id,
            transaction_id_order_id_dict={},
            traded_accounts=[
                [
                    test_engine.funded_50000_cognito_user_id,
                    test_engine.funded_50000_alpaca_account_id,
                    portfolio_id,
                ]
            ],
        )


@pytest.mark.integration
def test_public_to_private_after_deposit_marks_allocation_access_pending(
    test_engine: TestEngine,
):
    portfolio_id = None
    transaction_id_order_id_dict: dict[str, list[Order]] = {}
    try:
        portfolio_id = _create_portfolio(
            test_engine,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
            portfolio_name_prefix="access-public-private",
        )
        response = _deposit(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
        )
        _record_response(transaction_id_order_id_dict, response)

        _set_visibility(test_engine, portfolio_id=portfolio_id, visibility="PRIVATE")

        _assert_follower(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            expected=True,
        )
        _assert_access(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            granted_access_by="ALLOCATION",
            status="TO_BE_DELETED",
        )
    finally:
        _cleanup(
            test_engine,
            portfolio_id=portfolio_id,
            transaction_id_order_id_dict=transaction_id_order_id_dict,
            traded_accounts=[
                [
                    test_engine.funded_50000_cognito_user_id,
                    test_engine.funded_50000_alpaca_account_id,
                    portfolio_id,
                ]
            ],
        )


@pytest.mark.integration
def test_private_to_public_restores_pending_allocation_access(
    test_engine: TestEngine,
):
    portfolio_id = None
    transaction_id_order_id_dict: dict[str, list[Order]] = {}
    try:
        portfolio_id = _create_portfolio(
            test_engine,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
            portfolio_name_prefix="access-private-public",
        )
        response = _deposit(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
        )
        _record_response(transaction_id_order_id_dict, response)

        _set_visibility(test_engine, portfolio_id=portfolio_id, visibility="PRIVATE")
        _assert_access(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            granted_access_by="ALLOCATION",
            status="TO_BE_DELETED",
        )

        _set_visibility(test_engine, portfolio_id=portfolio_id, visibility="PUBLIC")
        _assert_access(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            granted_access_by="ALLOCATION",
            status="ACTIVE",
        )
    finally:
        _cleanup(
            test_engine,
            portfolio_id=portfolio_id,
            transaction_id_order_id_dict=transaction_id_order_id_dict,
            traded_accounts=[
                [
                    test_engine.funded_50000_cognito_user_id,
                    test_engine.funded_50000_alpaca_account_id,
                    portfolio_id,
                ]
            ],
        )


@pytest.mark.integration
def test_partial_withdraw_after_public_to_private_keeps_pending_access(
    test_engine: TestEngine,
):
    portfolio_id = None
    transaction_id_order_id_dict: dict[str, list[Order]] = {}
    try:
        portfolio_id = _create_portfolio(
            test_engine,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
            portfolio_name_prefix="access-private-partial-withdraw",
        )
        deposit_response = _deposit(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
        )
        _record_response(transaction_id_order_id_dict, deposit_response)
        _set_visibility(test_engine, portfolio_id=portfolio_id, visibility="PRIVATE")

        withdraw_response = _withdraw(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
        )
        _record_response(transaction_id_order_id_dict, withdraw_response)

        allocation = test_engine.allocation_repository.get_allocation(
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            allocation_id=portfolio_id,
        )
        assert allocation.open_positions is True
        _assert_follower(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            expected=True,
        )
        _assert_access(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            granted_access_by="ALLOCATION",
            status="TO_BE_DELETED",
        )
    finally:
        _cleanup(
            test_engine,
            portfolio_id=portfolio_id,
            transaction_id_order_id_dict=transaction_id_order_id_dict,
            traded_accounts=[
                [
                    test_engine.funded_50000_cognito_user_id,
                    test_engine.funded_50000_alpaca_account_id,
                    portfolio_id,
                ]
            ],
        )


@pytest.mark.integration
def test_withdraw_all_from_public_removes_follower_and_allocation_access(
    test_engine: TestEngine,
):
    portfolio_id = None
    transaction_id_order_id_dict: dict[str, list[Order]] = {}
    try:
        portfolio_id = _create_portfolio(
            test_engine,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
            portfolio_name_prefix="access-public-withdraw-all",
        )
        deposit_response = _deposit(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
        )
        _record_response(transaction_id_order_id_dict, deposit_response)
        _assert_access(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            granted_access_by="ALLOCATION",
            status="ACTIVE",
        )

        withdraw_response = _withdraw_all(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
        )
        _record_response(transaction_id_order_id_dict, withdraw_response)

        allocation = test_engine.allocation_repository.get_allocation(
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            allocation_id=portfolio_id,
        )
        assert allocation.open_positions is False
        _assert_follower(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            expected=False,
        )
        _assert_no_access(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
        )
    finally:
        _cleanup(
            test_engine,
            portfolio_id=portfolio_id,
            transaction_id_order_id_dict=transaction_id_order_id_dict,
            traded_accounts=[
                [
                    test_engine.funded_50000_cognito_user_id,
                    test_engine.funded_50000_alpaca_account_id,
                    portfolio_id,
                ]
            ],
        )


@pytest.mark.integration
def test_withdraw_all_after_public_to_private_removes_pending_allocation_access(
    test_engine: TestEngine,
):
    portfolio_id = None
    transaction_id_order_id_dict: dict[str, list[Order]] = {}
    try:
        portfolio_id = _create_portfolio(
            test_engine,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
            portfolio_name_prefix="access-private-withdraw-all",
        )
        deposit_response = _deposit(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
        )
        _record_response(transaction_id_order_id_dict, deposit_response)
        _set_visibility(test_engine, portfolio_id=portfolio_id, visibility="PRIVATE")
        _assert_access(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            granted_access_by="ALLOCATION",
            status="TO_BE_DELETED",
        )

        withdraw_response = _withdraw_all(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
        )
        _record_response(transaction_id_order_id_dict, withdraw_response)

        _assert_follower(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            expected=False,
        )
        _assert_no_access(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
        )
    finally:
        _cleanup(
            test_engine,
            portfolio_id=portfolio_id,
            transaction_id_order_id_dict=transaction_id_order_id_dict,
            traded_accounts=[
                [
                    test_engine.funded_50000_cognito_user_id,
                    test_engine.funded_50000_alpaca_account_id,
                    portfolio_id,
                ]
            ],
        )


@pytest.mark.integration
def test_withdraw_all_from_owner_granted_private_portfolio_preserves_access(
    test_engine: TestEngine,
):
    portfolio_id = None
    transaction_id_order_id_dict: dict[str, list[Order]] = {}
    try:
        portfolio_id = _create_portfolio(
            test_engine,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
            portfolio_name_prefix="access-owner-grant-private",
        )
        _set_visibility(test_engine, portfolio_id=portfolio_id, visibility="PRIVATE")
        _grant_owner_access(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
        )
        deposit_response = _deposit(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
        )
        _record_response(transaction_id_order_id_dict, deposit_response)
        _assert_access(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            granted_access_by="PORTFOLIO_OWNER",
            status="ACTIVE",
        )

        withdraw_response = _withdraw_all(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
        )
        _record_response(transaction_id_order_id_dict, withdraw_response)

        _assert_follower(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            expected=False,
        )
        _assert_access(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            granted_access_by="PORTFOLIO_OWNER",
            status="ACTIVE",
        )
    finally:
        _cleanup(
            test_engine,
            portfolio_id=portfolio_id,
            transaction_id_order_id_dict=transaction_id_order_id_dict,
            traded_accounts=[
                [
                    test_engine.funded_50000_cognito_user_id,
                    test_engine.funded_50000_alpaca_account_id,
                    portfolio_id,
                ]
            ],
        )


@pytest.mark.integration
def test_owner_grant_upgrades_pending_allocation_access_and_survives_withdraw_all(
    test_engine: TestEngine,
):
    portfolio_id = None
    transaction_id_order_id_dict: dict[str, list[Order]] = {}
    try:
        portfolio_id = _create_portfolio(
            test_engine,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
            portfolio_name_prefix="access-owner-upgrade",
        )
        deposit_response = _deposit(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
        )
        _record_response(transaction_id_order_id_dict, deposit_response)
        _set_visibility(test_engine, portfolio_id=portfolio_id, visibility="PRIVATE")
        _assert_access(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            granted_access_by="ALLOCATION",
            status="TO_BE_DELETED",
        )

        _grant_owner_access(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
        )
        _assert_access(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            granted_access_by="PORTFOLIO_OWNER",
            status="ACTIVE",
        )

        withdraw_response = _withdraw_all(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
        )
        _record_response(transaction_id_order_id_dict, withdraw_response)

        _assert_follower(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            expected=False,
        )
        _assert_access(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            granted_access_by="PORTFOLIO_OWNER",
            status="ACTIVE",
        )
    finally:
        _cleanup(
            test_engine,
            portfolio_id=portfolio_id,
            transaction_id_order_id_dict=transaction_id_order_id_dict,
            traded_accounts=[
                [
                    test_engine.funded_50000_cognito_user_id,
                    test_engine.funded_50000_alpaca_account_id,
                    portfolio_id,
                ]
            ],
        )


@pytest.mark.integration
def test_second_deposit_after_public_restore_keeps_single_active_allocation_access(
    test_engine: TestEngine,
):
    portfolio_id = None
    transaction_id_order_id_dict: dict[str, list[Order]] = {}
    try:
        portfolio_id = _create_portfolio(
            test_engine,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
            portfolio_name_prefix="access-second-deposit",
        )
        first_deposit_response = _deposit(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
        )
        _record_response(transaction_id_order_id_dict, first_deposit_response)
        _set_visibility(test_engine, portfolio_id=portfolio_id, visibility="PRIVATE")
        _set_visibility(test_engine, portfolio_id=portfolio_id, visibility="PUBLIC")

        second_deposit_response = _deposit(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            alpaca_account_id=test_engine.funded_50000_alpaca_account_id,
            portfolio_owner_cognito_user_id=test_engine.portfolio_owner_cognito_user_id,
            amount=50.0,
        )
        _record_response(transaction_id_order_id_dict, second_deposit_response)

        _assert_access(
            test_engine,
            portfolio_id=portfolio_id,
            cognito_user_id=test_engine.funded_50000_cognito_user_id,
            granted_access_by="ALLOCATION",
            status="ACTIVE",
        )
        assert (
            _access_count(
                test_engine,
                portfolio_id=portfolio_id,
                cognito_user_id=test_engine.funded_50000_cognito_user_id,
            )
            == 1
        )
    finally:
        _cleanup(
            test_engine,
            portfolio_id=portfolio_id,
            transaction_id_order_id_dict=transaction_id_order_id_dict,
            traded_accounts=[
                [
                    test_engine.funded_50000_cognito_user_id,
                    test_engine.funded_50000_alpaca_account_id,
                    portfolio_id,
                ]
            ],
        )
