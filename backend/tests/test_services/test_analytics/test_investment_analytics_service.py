from __future__ import annotations

from pathlib import Path
import sys
from uuid import uuid4

from dotenv import load_dotenv
import pytest

repo_root = Path(__file__).resolve().parents[4]
backend_dir = Path(__file__).resolve().parents[3]
for import_path in (str(backend_dir), str(repo_root)):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

from core import deps as app_deps
from core.config import get_settings
from services.investment_analytics_service import (
    InvestmentAnalyticsInternalServerError,
    InvestmentAnalyticsService,
)

DEV_FUNDED_50000_ALPACA_ACCOUNT_ID = "49243cf6-8cd6-4511-a5c0-00ac6bc1a27c"
DEV_FUNDED_50000_COGNITO_USER_ID = "04484408-a0d1-70d6-fc4c-9b1d01f18fa2"

TEST_FUNDED_50000_ALPACA_ACCOUNT_ID = "c83885b1-e24a-4d3e-bbd6-1de518837938"
TEST_FUNDED_50000_COGNITO_USER_ID = "e46834b8-6091-70a3-1135-bccdc6174b07"

load_dotenv(repo_root / ".env")
get_settings.cache_clear()


def _funded_account_ids() -> tuple[str, str]:
    env_prefix = get_settings().env.upper()
    return (
        globals()[f"{env_prefix}_FUNDED_50000_ALPACA_ACCOUNT_ID"],
        globals()[f"{env_prefix}_FUNDED_50000_COGNITO_USER_ID"],
    )


@pytest.fixture(scope="session")
def investment_analytics_service() -> InvestmentAnalyticsService:
    app_deps.get_boto3_session.cache_clear()
    app_deps.get_dynamodb_resource_cached.cache_clear()
    app_deps.get_alpaca_broker_client.cache_clear()
    app_deps.get_allocation_dynamodb_client.cache_clear()

    alpaca_broker_client = app_deps.get_alpaca_broker_client()
    allocation_repository = app_deps.get_allocation_repository(
        alpaca_broker_client=alpaca_broker_client,
        allocation_dynamodb_client=(
            app_deps.get_allocation_dynamodb_client()
        ),
    )
    return app_deps.get_investment_analytics_service(
        alpaca_broker_client=alpaca_broker_client,
        allocation_repository=allocation_repository,
    )


def test_investment_analytics_error_class_sets_code() -> None:
    error = InvestmentAnalyticsInternalServerError(
        "failed",
        code="INVESTMENT_ANALYTICS_CUSTOM",
    )

    assert str(error) == "failed"
    assert error.code == "INVESTMENT_ANALYTICS_CUSTOM"


@pytest.mark.integration
def test_investment_analytics_account_summary_for_funded_account(
    investment_analytics_service: InvestmentAnalyticsService,
) -> None:
    alpaca_account_id, cognito_user_id = _funded_account_ids()

    analytics = investment_analytics_service.get_account_analytics(
        cognito_user_id=cognito_user_id,
        alpaca_account_id=alpaca_account_id,
    )

    assert analytics["equity_graph"] is not None
    assert analytics["equity_graph"]
    for period in ("1D", "1W", "1M", "3M", "1A", "ALL"):
        assert period in analytics["equity_graph"]
        assert analytics["equity_graph"][period]["equity"] is not None
        assert analytics["equity_graph"][period]["timestamp"] is not None

    assert analytics["cash"] is not None
    assert isinstance(analytics["cash"], float)
    assert analytics["equity"] is not None
    assert isinstance(analytics["equity"], float)
    assert analytics["portfolio_allocations"] is not None
    assert isinstance(analytics["portfolio_allocations"], dict)


# @pytest.mark.integration
# def test_investment_analytics_missing_portfolio_allocation_returns_empty_values(
#     investment_analytics_service: InvestmentAnalyticsService,
# ) -> None:
#     _, cognito_user_id = _funded_account_ids()
#     missing_portfolio_id = f"missing-investment-analytics-{uuid4()}"

#     assert investment_analytics_service.get_portfolio_allocation_analytics(
#         cognito_user_id=cognito_user_id,
#         portfolio_id=missing_portfolio_id,
#     ) == {}
#     assert investment_analytics_service.get_portfolio_allocation_transactions(
#         cognito_user_id=cognito_user_id,
#         portfolio_id=missing_portfolio_id,
#     ) == []


@pytest.mark.integration
def test_investment_analytics_get_stock_by_stock_id(
    investment_analytics_service: InvestmentAnalyticsService,
) -> None:
    aapl = investment_analytics_service.alpaca_broker_client.get_stock_by_symbol(
        symbol="AAPL"
    )

    stock = investment_analytics_service.get_stock_by_stock_id(
        stock_id=aapl.stock_id,
    )

    assert stock.symbol == "AAPL"
    assert stock.stock_id == aapl.stock_id


@pytest.mark.integration
def test_investment_analytics_wraps_invalid_account_errors(
    investment_analytics_service: InvestmentAnalyticsService,
) -> None:
    with pytest.raises(InvestmentAnalyticsInternalServerError) as exc_info:
        investment_analytics_service.get_account_analytics(
            cognito_user_id=f"missing-user-{uuid4()}",
            alpaca_account_id=str(uuid4()),
        )

    assert exc_info.value.code == "INVESTMENT_ANALYTICS_SERVICE_ERROR"
