from decimal import Decimal
from time import sleep

import pytest
from alpaca.broker.enums import BankAccountType, TransferDirection, TransferTiming

from conftest import TestEngine


def _response_value(response, key: str):
    if isinstance(response, dict):
        return response.get(key)
    return getattr(response, key, None)


@pytest.mark.integration
def test_create_account_fund_account(test_engine: TestEngine):
    baskt_account = test_engine.test_create_baskt_account()
    funding_amount = Decimal("100.00")

    ach_relationship = test_engine.account_lifecycle_service.create_ach_relationship(
        alpaca_account_id=baskt_account.alpaca_account_id,
        cognito_user_id=baskt_account.cognito_user_id,
        account_owner_name="Jane Q Tester",
        bank_account_type=BankAccountType.CHECKING,
        bank_account_number="123456789",
        bank_routing_number="121000358",
        nickname="Sandbox Checking",
    )
    ach_relationship_id = _response_value(ach_relationship, "id")
    assert ach_relationship_id is not None

    initial_trade_account = test_engine.alpaca_broker_client.client.get_trade_account_by_id(
        account_id=baskt_account.alpaca_account_id
    )
    initial_cash = Decimal(str(getattr(initial_trade_account, "last_cash", "0") or "0"))

    transfer = test_engine.account_lifecycle_service.create_ach_transfer_request(
        alpaca_account_id=baskt_account.alpaca_account_id,
        cognito_user_id=baskt_account.cognito_user_id,
        relationship_id=ach_relationship_id,
        amount=str(funding_amount),
        direction=TransferDirection.INCOMING,
        timing=TransferTiming.IMMEDIATE,
    )

    assert Decimal(str(_response_value(transfer, "amount"))) == funding_amount
    assert _response_value(transfer, "relationship_id") is not None

    expected_cash = initial_cash + funding_amount
    latest_cash = initial_cash
    for _ in range(18):
        trade_account = test_engine.alpaca_broker_client.client.get_trade_account_by_id(
            account_id=baskt_account.alpaca_account_id
        )
        latest_cash = Decimal(str(getattr(trade_account, "last_cash", "0") or "0"))
        if latest_cash >= expected_cash:
            break
        sleep(10)

    assert latest_cash >= expected_cash
