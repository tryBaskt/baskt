import pytest
from alpaca.broker.enums import BankAccountType

from conftest import TestEngine


@pytest.mark.integration
def test_create_account_fund_account(test_engine: TestEngine):
    baskt_account = test_engine.test_create_baskt_account()
    funding_result = test_engine.fund_baskt_account(
        baskt_account=baskt_account
    )