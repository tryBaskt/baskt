import pytest
from conftest import TestEngine
from backend.domain.model_portfolio import ModelPortfolio, ModelPortfolioPosition, ModelPortfolioSnapshot
import uuid
from datetime import datetime, timezone, timedelta


PORTFOLIO_OWNER_ALPACA_ACCOUNT_ID = "004989ae-a5eb-4ea1-b525-3eab8bf5a5aa"
PORTFOLIO_OWNER_COGNITO_USER_ID = "c46894f8-e091-7088-e0fd-35d1d15bffb7"

def _create_portfolio(
    test_engine: TestEngine,
    portfolio_owner_cognito_user_id: str,
    *,
    portfolio_name_prefix: str,
    symbols: list[str],
    directions: list[int],
    target_weights: list[float],
    leverages: list[float],
    creation_time: datetime

) -> str:
    return test_engine.test_create_portfolio(
        symbols=symbols,
        directions=directions,
        target_weights=target_weights,
        leverages=leverages,
        portfolio_name=f"{portfolio_name_prefix}-{uuid.uuid4()}",
        portfolio_owner_cognito_user_id=portfolio_owner_cognito_user_id,
        creation_time=creation_time
    )

@pytest.mark.integration
def test_basic_one_month_one_symbol(test_engine: TestEngine):

    symbols = ["AAPL"]
    directions = [1]
    target_weights = [100]
    leverages = [1.00]
    creation_time = datetime(year=2026, month=1, day=20, hour=14, minute=30, second=0, microsecond=0, tzinfo=timezone.utc)
    current_datetime = creation_time + timedelta(days=30)

    portfolio_id = _create_portfolio(
        test_engine=test_engine,
        portfolio_owner_cognito_user_id=PORTFOLIO_OWNER_COGNITO_USER_ID,
        portfolio_name_prefix="pytest-basic-test",
        symbols=symbols,
        directions=directions,
        target_weights=target_weights,
        leverages=leverages,
        creation_time=creation_time
    )

    analytics_response =test_engine.model_portfolio_analytics_service.get_model_portfolio_bars(
        portfolio_id=portfolio_id,
        current_datetime=current_datetime
    )
    print("Model portfolio analytics: ", analytics_response["1M"])

    backtest_response = test_engine.backtest_service.run_backtest(
        start_date=(creation_time + timedelta(days=1)).date().isoformat(),
        end_date=(creation_time + timedelta(days=29)).date().isoformat(),
        positions_conf=[
            {
            "symbol": "AAPL",
            "target_weight": 100.0,
            "direction": 1,
            "leverage": 1.00,
            }
        ]
    )

    print("backtest response: ", backtest_response)
