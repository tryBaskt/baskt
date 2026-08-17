from __future__ import annotations

import os
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
from services.allocation_analytics_service import (
    AllocationAnalyticsInternalServerError,
    AllocationAnalyticsService,
)

load_dotenv(repo_root / ".env")
get_settings.cache_clear()


def _required_env_value(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required for allocation analytics tests.")
    return value


def _funded_account_ids() -> tuple[str, str]:
    env_prefix = get_settings().env.upper()
    return (
        _required_env_value(f"{env_prefix}_TEST_USER_1_ALPACA_ACCOUNT_ID"),
        _required_env_value(f"{env_prefix}_TEST_USER_1_COGNITO_USER_ID"),
    )


@pytest.fixture(scope="session")
def allocation_analytics_service() -> AllocationAnalyticsService:
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
    return app_deps.get_allocation_analytics_service(
        alpaca_broker_client=alpaca_broker_client,
        allocation_repository=allocation_repository,
    )


def test_allocation_analytics_error_class_sets_code() -> None:
    error = AllocationAnalyticsInternalServerError(
        "failed",
        code="ALLOCATION_ANALYTICS_CUSTOM",
    )

    assert str(error) == "failed"
    assert error.code == "ALLOCATION_ANALYTICS_CUSTOM"


@pytest.mark.integration
def test_allocation_analytics_account_summary_for_funded_account(
    allocation_analytics_service: AllocationAnalyticsService,
) -> None:
    alpaca_account_id, cognito_user_id = _funded_account_ids()

    analytics = allocation_analytics_service.get_all_active_allocation_analytics(
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
    assert analytics["allocations"] is not None
    assert isinstance(analytics["allocations"], dict)


# @pytest.mark.integration
# def test_allocation_analytics_missing_portfolio_allocation_returns_empty_values(
#     allocation_analytics_service: AllocationAnalyticsService,
# ) -> None:
#     _, cognito_user_id = _funded_account_ids()
#     missing_portfolio_id = f"missing-allocation-analytics-{uuid4()}"

#     assert allocation_analytics_service.get_portfolio_allocation_analytics(
#         cognito_user_id=cognito_user_id,
#         portfolio_id=missing_portfolio_id,
#     ) == {}
#     assert allocation_analytics_service.get_portfolio_allocation_transaction_history(
#         cognito_user_id=cognito_user_id,
#         portfolio_id=missing_portfolio_id,
#     ) == []


@pytest.mark.integration
def test_allocation_analytics_wraps_invalid_account_errors(
    allocation_analytics_service: AllocationAnalyticsService,
) -> None:
    with pytest.raises(AllocationAnalyticsInternalServerError) as exc_info:
        allocation_analytics_service.get_all_active_allocation_analytics(
            cognito_user_id=f"missing-user-{uuid4()}",
            alpaca_account_id=str(uuid4()),
        )

    assert exc_info.value.code == "ALLOCATION_ANALYTICS_SERVICE_ERROR"
