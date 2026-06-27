import uuid

import pytest

from conftest import (
    FUNDED_ALPACA_ACCOUNT_ID,
    FUNDED_COGNITO_USER_ID,
    TestEngine,
)


@pytest.mark.integration
def test_queue_stock_buy_executes_in_alpaca_sandbox(test_engine: TestEngine):
    asset_id = str(uuid.uuid4())

    test_engine.test_queue_stock_buy(
        symbol="AAPL",
        asset_id=asset_id,
        amount=10.0,
        cognito_user_id=FUNDED_COGNITO_USER_ID,
        alpaca_account_id=FUNDED_ALPACA_ACCOUNT_ID,
    )
