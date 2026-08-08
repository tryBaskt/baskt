from __future__ import annotations

import os
from datetime import date, datetime, timezone
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

from clients.alpaca_broker_client import (
    AlpacaBrokerClient,
    AlpacaBrokerClientError,
)
from core import deps as app_deps
from core.config import get_settings

load_dotenv(repo_root / ".env")
get_settings.cache_clear()


def _required_env_value(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required for Alpaca broker client tests.")
    return value


@pytest.fixture(scope="session")
def alpaca_broker_client() -> AlpacaBrokerClient:
    app_deps.get_alpaca_broker_client.cache_clear()
    return app_deps.get_alpaca_broker_client()


@pytest.fixture(scope="session")
def funded_account_ids() -> tuple[str, str]:
    env_prefix = get_settings().env.upper()
    return (
        _required_env_value(f"{env_prefix}_TEST_USER_1_ALPACA_ACCOUNT_ID"),
        _required_env_value(f"{env_prefix}_TEST_USER_1_COGNITO_USER_ID"),
    )


def _assert_client_error(exc_info: pytest.ExceptionInfo, code: str) -> None:
    assert exc_info.value.code == code


@pytest.mark.integration
def test_alpaca_broker_client_fetches_real_tradeable_fractionable_us_assets(
    alpaca_broker_client: AlpacaBrokerClient,
) -> None:
    assets = alpaca_broker_client.get_tradeable_fractionable_US_assets()

    assert assets
    assert all(asset.tradable for asset in assets[:25])
    assert all(asset.fractionable for asset in assets[:25])


@pytest.mark.integration
def test_alpaca_broker_client_get_stock_by_symbol_and_asset_id(
    alpaca_broker_client: AlpacaBrokerClient,
) -> None:
    stock = alpaca_broker_client.get_stock_by_symbol(symbol="AAPL")

    assert stock is not None
    assert stock.symbol == "AAPL"
    assert stock.tradable is True
    assert alpaca_broker_client.get_stock_by_asset_id(
        asset_id=stock.stock_id
    ).symbol == "AAPL"
    assert alpaca_broker_client.get_stock_by_symbol(
        symbol=f"ZZZ{uuid4().hex[:8].upper()}"
    ) is None

    with pytest.raises(AlpacaBrokerClientError) as exc_info:
        alpaca_broker_client.get_stock_by_symbol(symbol=" ")
    _assert_client_error(exc_info, "ALPACA_BROKER_STOCK_SYMBOL_REQUIRED")


@pytest.mark.integration
def test_alpaca_broker_client_market_calendar_and_price_data(
    alpaca_broker_client: AlpacaBrokerClient,
) -> None:
    sessions = alpaca_broker_client.get_stock_market_calendar(
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
    )
    assert sessions

    prices = alpaca_broker_client.get_stock_prices_over_time(
        symbols=["AAPL"],
        start_datetime=datetime(2024, 1, 2, tzinfo=timezone.utc),
        end_datetime=datetime(2024, 1, 4, tzinfo=timezone.utc),
        timeframe="1D",
    )
    assert not prices.empty
    assert "AAPL" in prices.columns

    price_at_time = alpaca_broker_client.get_stock_prices_at_time(
        symbols=["AAPL"],
        timestamp=datetime(2024, 1, 2, 20, 0, tzinfo=timezone.utc),
    )
    assert list(price_at_time.columns) == ["symbol", "price", "timestamp"]
    assert price_at_time.iloc[0]["symbol"] == "AAPL"
    assert price_at_time.iloc[0]["price"] > 0
    assert price_at_time.iloc[0]["timestamp"] <= datetime(
        2024,
        1,
        2,
        20,
        0,
        tzinfo=timezone.utc,
    )


def test_alpaca_broker_client_rejects_invalid_market_data_inputs(
    alpaca_broker_client: AlpacaBrokerClient,
) -> None:
    with pytest.raises(AlpacaBrokerClientError) as calendar_error:
        alpaca_broker_client.get_stock_market_calendar(
            start_date=date(2024, 1, 3),
            end_date=date(2024, 1, 2),
        )
    _assert_client_error(
        calendar_error,
        "ALPACA_BROKER_MARKET_CALENDAR_INVALID_RANGE",
    )

    with pytest.raises(AlpacaBrokerClientError) as prices_error:
        alpaca_broker_client.get_stock_prices_over_time(
            symbols=["AAPL"],
            start_datetime=datetime(2024, 1, 2),
            end_datetime=datetime(2024, 1, 3, tzinfo=timezone.utc),
            timeframe="1D",
        )
    _assert_client_error(
        prices_error,
        "ALPACA_BROKER_STOCK_PRICES_START_TIMEZONE_REQUIRED",
    )

    with pytest.raises(AlpacaBrokerClientError) as end_time_error:
        alpaca_broker_client.get_stock_prices_over_time(
            symbols=["AAPL"],
            start_datetime=datetime(2024, 1, 2, tzinfo=timezone.utc),
            end_datetime=datetime(2024, 1, 3),
            timeframe="1D",
        )
    _assert_client_error(
        end_time_error,
        "ALPACA_BROKER_STOCK_PRICES_END_TIMEZONE_REQUIRED",
    )

    with pytest.raises(AlpacaBrokerClientError) as point_error:
        alpaca_broker_client.get_stock_prices_at_time(
            symbols=["AAPL"],
            timestamp=datetime(2024, 1, 2),
        )
    _assert_client_error(point_error, "ALPACA_BROKER_STOCK_PRICE_TIMEZONE_REQUIRED")


@pytest.mark.integration
def test_alpaca_broker_client_account_read_wrappers(
    alpaca_broker_client: AlpacaBrokerClient,
    funded_account_ids: tuple[str, str],
) -> None:
    alpaca_account_id, cognito_user_id = funded_account_ids

    account = alpaca_broker_client.get_alpaca_account_by_id(
        account_id=alpaca_account_id,
        cognito_user_id=cognito_user_id,
    )
    trade_account = alpaca_broker_client.get_trade_account(
        account_id=alpaca_account_id,
        cognito_user_id=cognito_user_id,
    )
    portfolio_history = alpaca_broker_client.get_portfolio_history(
        alpaca_account_id=alpaca_account_id,
    )

    assert str(account.id) == alpaca_account_id
    assert trade_account is not None
    assert set(portfolio_history) == {"1D", "1W", "1M", "3M", "1A", "ALL"}


@pytest.mark.integration
def test_alpaca_broker_client_position_and_relationship_reads(
    alpaca_broker_client: AlpacaBrokerClient,
    funded_account_ids: tuple[str, str],
) -> None:
    alpaca_account_id, cognito_user_id = funded_account_ids

    assert isinstance(
        alpaca_broker_client.get_baskt_positions_dict(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        ),
        dict,
    )
    assert isinstance(
        alpaca_broker_client.get_ach_relationships(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        ),
        list,
    )
    assert isinstance(
        alpaca_broker_client.get_banks(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        ),
        list,
    )
    assert isinstance(
        alpaca_broker_client.get_transfers(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
        ),
        list,
    )


@pytest.mark.integration
def test_alpaca_broker_client_missing_position_and_latest_price_paths(
    alpaca_broker_client: AlpacaBrokerClient,
    funded_account_ids: tuple[str, str],
) -> None:
    alpaca_account_id, cognito_user_id = funded_account_ids
    stock = alpaca_broker_client.get_stock_by_symbol(symbol="AAPL")

    assert stock is not None
    assert alpaca_broker_client.get_latest_price([]) == {}
    assert alpaca_broker_client.get_latest_price(["AAPL"])["AAPL"] > 0
    assert (
        alpaca_broker_client.get_position_by_asset_id(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
            asset_id=stock.stock_id,
            error_if_no_position=False,
        )
        is None
    )

    with pytest.raises(AlpacaBrokerClientError) as exc_info:
        alpaca_broker_client.get_position_by_asset_id(
            alpaca_account_id=alpaca_account_id,
            cognito_user_id=cognito_user_id,
            asset_id=stock.stock_id,
            error_if_no_position=True,
        )
    _assert_client_error(exc_info, "ALPACA_BROKER_GET_POSITION_BY_ASSET_ID_FAILED")
