"""Unit tests for transfer cancellation."""

from unittest.mock import MagicMock

import pytest

from clients.alpaca_broker_client import AlpacaBrokerClient, AlpacaBrokerClientError
from services.account_lifecycle_service import (
    AccountLifecycleInternalServerError,
    AccountLifecycleService,
)


def test_alpaca_client_cancels_transfer_for_account() -> None:
    client = AlpacaBrokerClient.__new__(AlpacaBrokerClient)
    client.client = MagicMock()

    client.cancel_transfer(
        cognito_user_id="cognito-user",
        alpaca_account_id="alpaca-account",
        transfer_id="transfer-id",
    )

    client.client.cancel_transfer_for_account.assert_called_once_with(
        account_id="alpaca-account",
        transfer_id="transfer-id",
    )


def test_alpaca_client_wraps_cancel_failure() -> None:
    client = AlpacaBrokerClient.__new__(AlpacaBrokerClient)
    client.client = MagicMock()
    client.client.cancel_transfer_for_account.side_effect = RuntimeError("failure")

    with pytest.raises(AlpacaBrokerClientError) as exc_info:
        client.cancel_transfer(
            cognito_user_id="cognito-user",
            alpaca_account_id="alpaca-account",
            transfer_id="transfer-id",
        )

    assert exc_info.value.code == "ALPACA_BROKER_CANCEL_TRANSFER_FAILED"


def test_service_wraps_alpaca_cancel_failure() -> None:
    alpaca_client = MagicMock()
    alpaca_client.cancel_transfer.side_effect = AlpacaBrokerClientError(
        message="failure",
        code="ALPACA_BROKER_CANCEL_TRANSFER_FAILED",
    )
    service = AccountLifecycleService(
        alpaca_broker_client=alpaca_client,
        cognito_client=MagicMock(),
        baskt_account_repository=MagicMock(),
    )

    with pytest.raises(AccountLifecycleInternalServerError) as exc_info:
        service.cancel_transfer(
            cognito_user_id="cognito-user",
            alpaca_account_id="alpaca-account",
            transfer_id="transfer-id",
        )

    assert exc_info.value.code == "ACCOUNT_LIFECYCLE_CANCEL_TRANSFER_FAILED"
