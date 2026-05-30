import uuid
import pytest
from conftest import TestEngine

@pytest.mark.integration
def test_basic_deposit(test_engine: TestEngine):
    baskt_account = test_engine.test_create_baskt_account()
    try:
        portfolio_name = f"pytest-dep-wd-realize-{uuid.uuid4()}"
        symbols = [
            "AAPL"
        ]
        directions = [1]
        target_weights = [1.00]
        leverages = [1.0] * len(symbols)
        portfolio_id = test_engine.test_create_portfolio(
            symbols=symbols,directions=directions, target_weights=target_weights,leverages=leverages,
            portfolio_name=portfolio_name, portfolio_owner_cognito_user_id=baskt_account.cognito_user_id
        )
    finally:
        pass