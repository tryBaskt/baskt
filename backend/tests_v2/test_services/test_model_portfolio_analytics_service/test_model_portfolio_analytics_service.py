from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from clients.dynamodb_client import to_dynamodb_value
from domain.model_portfolio_domain import (
    ModelPortfolioAnalyticsPosition,
    ModelPortfolioAnalyticsSnapshot,
    ModelPortfolioPosition,
    ModelPortfolioSnapshot,
)
from repository.model_portfolio_repository import ModelPortfolioRepository
from services.asset_analytics_service import AssetAnalyticsService
from services.model_portfolio_analytics_service import (
    ModelPortfolioAnalyticsInternalServerError,
    ModelPortfolioAnalyticsService,
)


"""
These tests exercise ModelPortfolioAnalyticsService with integrated dependencies.

Coverage goals:
- get_one_day_session_bounds(): resolve active trading day, after-hours weekday,
  before-open weekday, holiday, weekend, UTC-date/market-date mismatch, exact
  market open/close, and early-close sessions through the real market calendar.
- get_one_day_session_bounds(): reject naive, Eastern, Pacific, and fixed-offset
  non-UTC current_datetime values before calendar lookup.
- get_one_day_session_bounds(): raise when the real calendar returns no usable
  active or completed session before current_datetime.
- get_positions_updated_weights(): use real point-in-time asset prices at known
  start/end datetimes, independently calculate expected weights for mixed
  long/short, long-only, and short-only snapshots, and compare those expected
  weights to the service output.
- get_analytics_snapshots(): verify empty windows, delta-derived and explicit
  period starts, all-period starts, lookback-window snapshot counts,
  chronological ordering, target weights for in-window snapshots, recalculated
  boundary weights, current-time inclusion, future-snapshot exclusion, and
  minute rounding.
- get_stock_prices_at_snapshot_changes(): verify no-op empty snapshots, first
  snapshot prices, changed-symbol transitions, multiple transitions, existing
  price preservation, sorted/named index, and provider-returned timestamps.
- get_model_portfolio_bars(): persist model portfolios, read them through the
  real repository path, verify the default periods/timeframes, aligned UTC
  chart data, session/lookback/all-time windows, rebalance stitching,
  long/short exposure metrics, final-return and max-drawdown consistency,
  benchmark-aligned metric fields, unusable-period omission, snapshot sorting,
  non-UTC current_datetime rejection, and natural invalid-symbol failure.
- _calculate_model_portfolio_period(): omit empty analytics only when no market
  trading time has elapsed since portfolio creation; raise when trading time
  elapsed but benchmark-aligned analytics cannot be calculated.
"""


MARKET_TIMEZONE = ZoneInfo("America/New_York")


def _market_datetime(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int = 0,
) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=MARKET_TIMEZONE)


def _utc_datetime(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int = 0,
) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _snapshot(
    positions: list[ModelPortfolioPosition],
    *,
    timestamp: datetime | None = None,
    snapshot_id: str = "test-snapshot",
) -> ModelPortfolioSnapshot:
    return ModelPortfolioSnapshot(
        positions=positions,
        timestamp=timestamp or _utc_datetime(2024, 7, 5, 13, 30),
        snapshot_id=snapshot_id,
    )


def _position(
    *,
    symbol: str,
    direction: int,
    leverage: float,
    model_filled_quantity: float,
    model_filled_avg_price: float,
    target_weight: float = 0.0,
) -> ModelPortfolioPosition:
    return ModelPortfolioPosition(
        symbol=symbol,
        target_weight=target_weight,
        direction=direction,
        leverage=leverage,
        model_filled_quantity=model_filled_quantity,
        model_filled_avg_price=model_filled_avg_price,
    )


def _analytics_snapshot(
    *,
    symbols: list[str],
    timestamp: datetime,
) -> ModelPortfolioAnalyticsSnapshot:
    return ModelPortfolioAnalyticsSnapshot(
        positions=[
            ModelPortfolioAnalyticsPosition(
                symbol=symbol,
                direction=1,
                leverage=1.0,
                current_weight=1.0 / len(symbols),
            )
            for symbol in symbols
        ],
        timestamp=timestamp,
    )


def _expected_updated_weights(
    *,
    snapshot: ModelPortfolioSnapshot,
    start_prices: dict[str, float],
    end_prices: dict[str, float],
) -> dict[str, float]:
    end_position_values: dict[str, float] = {}
    for position in snapshot.positions:
        start_price = start_prices[position.symbol]
        end_price = end_prices[position.symbol]
        start_position_value = position.model_filled_quantity * (
            position.model_filled_avg_price
            + position.direction
            * (start_price - position.model_filled_avg_price)
        )
        end_position_values[position.symbol] = start_position_value * (
            1
            + position.direction
            * position.leverage
            * ((end_price / start_price) - 1)
        )

    total_end_value = sum(end_position_values.values())
    return {
        symbol: position_value / total_end_value
        for symbol, position_value in end_position_values.items()
    }


def _raw_position(
    *,
    symbol: str,
    target_weight: float,
    direction: int,
    leverage: float,
    model_filled_quantity: float,
    model_filled_avg_price: float,
) -> dict:
    return {
        "symbol": symbol,
        "target_weight": target_weight,
        "direction": direction,
        "leverage": leverage,
        "model_filled_quantity": model_filled_quantity,
        "model_filled_avg_price": model_filled_avg_price,
    }


def _raw_snapshot(
    *,
    timestamp: datetime,
    positions: list[dict],
) -> dict:
    return {
        "snapshot_id": str(uuid4()),
        "timestamp": timestamp.isoformat(),
        "positions": positions,
    }


def _persist_raw_model_portfolio(
    *,
    model_portfolio_repository: ModelPortfolioRepository,
    owner_cognito_user_id: str,
    snapshots: list[dict],
) -> str:
    portfolio_id = str(uuid4())
    snapshot_timestamps = [
        datetime.fromisoformat(snapshot["timestamp"])
        for snapshot in snapshots
    ]
    created_at = min(snapshot_timestamps) if snapshot_timestamps else _utc_datetime(
        2024,
        7,
        10,
        15,
        30,
    )
    updated_at = max(snapshot_timestamps) if snapshot_timestamps else created_at
    model_portfolio_repository.dynamodb.put_item(
        item=to_dynamodb_value(
            {
                "portfolio_id": portfolio_id,
                "portfolio_owner_cognito_user_id": owner_cognito_user_id,
                "portfolio_name": f"Tests V2 Analytics Portfolio {portfolio_id}",
                "position_history": snapshots,
                "created_at": created_at.isoformat(),
                "updated_at": updated_at.isoformat(),
                "description": "tests-v2 analytics portfolio",
                "visibility": "PRIVATE",
            }
        )
    )
    return portfolio_id


def _delete_model_portfolio(
    *,
    model_portfolio_repository: ModelPortfolioRepository,
    portfolio_id: str | None,
) -> None:
    if portfolio_id is not None:
        model_portfolio_repository.dynamodb.delete_item(
            key={"portfolio_id": portfolio_id}
        )


def _persist_bars_portfolio(
    *,
    model_portfolio_repository: ModelPortfolioRepository,
    owner_cognito_user_id: str,
    snapshots: list[dict] | None = None,
) -> str:
    return _persist_raw_model_portfolio(
        model_portfolio_repository=model_portfolio_repository,
        owner_cognito_user_id=owner_cognito_user_id,
        snapshots=snapshots
        or [
            _raw_snapshot(
                timestamp=_utc_datetime(2023, 7, 3, 14),
                positions=[
                    _raw_position(
                        symbol="AAPL",
                        target_weight=0.55,
                        direction=1,
                        leverage=1.0,
                        model_filled_quantity=24.0,
                        model_filled_avg_price=192.0,
                    ),
                    _raw_position(
                        symbol="MSFT",
                        target_weight=0.45,
                        direction=-1,
                        leverage=1.0,
                        model_filled_quantity=10.0,
                        model_filled_avg_price=338.0,
                    ),
                ],
            ),
            _raw_snapshot(
                timestamp=_utc_datetime(2024, 6, 10, 14),
                positions=[
                    _raw_position(
                        symbol="AAPL",
                        target_weight=0.6,
                        direction=1,
                        leverage=1.0,
                        model_filled_quantity=28.0,
                        model_filled_avg_price=193.0,
                    ),
                    _raw_position(
                        symbol="GOOG",
                        target_weight=0.4,
                        direction=1,
                        leverage=1.0,
                        model_filled_quantity=22.0,
                        model_filled_avg_price=176.0,
                    ),
                ],
            ),
            _raw_snapshot(
                timestamp=_utc_datetime(2024, 7, 9, 14),
                positions=[
                    _raw_position(
                        symbol="MSFT",
                        target_weight=0.35,
                        direction=1,
                        leverage=1.0,
                        model_filled_quantity=8.0,
                        model_filled_avg_price=460.0,
                    ),
                    _raw_position(
                        symbol="GOOG",
                        target_weight=0.65,
                        direction=-1,
                        leverage=1.0,
                        model_filled_quantity=20.0,
                        model_filled_avg_price=190.0,
                    ),
                ],
            ),
        ],
    )


def _assert_metric_is_valid(value: float | None) -> None:
    if value is not None:
        assert math.isfinite(value)


def _assert_period_payload_is_valid(
    *,
    period_response: dict,
    expected_timeframe: str,
) -> None:
    timestamps = period_response["timestamp"]
    cumulative_returns = period_response["cumulative_returns"]

    assert period_response["timeframe"] == expected_timeframe
    assert timestamps
    assert cumulative_returns
    assert len(timestamps) == len(cumulative_returns)
    assert timestamps == sorted(timestamps)
    assert len(timestamps) == len(set(timestamps))
    for timestamp in timestamps:
        assert timestamp.tzinfo is not None
        assert timestamp.utcoffset() == timedelta(0)
    for cumulative_return in cumulative_returns:
        assert isinstance(cumulative_return, float)
        assert math.isfinite(cumulative_return)

    assert period_response["final_cumulative_return"] == pytest.approx(
        cumulative_returns[-1] / 100.0
    )

    equity_curve = [
        1.0 + cumulative_return / 100.0
        for cumulative_return in cumulative_returns
    ]
    running_peak = equity_curve[0]
    drawdowns = []
    for equity_value in equity_curve:
        running_peak = max(running_peak, equity_value)
        drawdowns.append((equity_value / running_peak) - 1.0)
    assert period_response["maximum_drawdown"] == pytest.approx(min(drawdowns))

    for metric_name in [
        "cagr",
        "annualized_volatility",
        "leverage_adjusted_direction",
        "alpha",
        "beta",
        "sharpe_ratio",
        "maximum_drawdown",
        "maximum_drawdown_duration",
    ]:
        _assert_metric_is_valid(period_response[metric_name])


def test_get_one_day_session_bounds_active_trading_day_ends_at_current_time(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
) -> None:
    current_datetime = _utc_datetime(2024, 7, 5, 15, 15)

    session_start, session_end = (
        model_portfolio_analytics_service.get_one_day_session_bounds(
            current_datetime
        )
    )

    assert session_start == _utc_datetime(2024, 7, 5, 13, 30)
    assert session_end == current_datetime


def test_get_one_day_session_bounds_after_hours_weekday_returns_completed_session(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
) -> None:
    current_datetime = _utc_datetime(2024, 7, 5, 22)

    session_start, session_end = (
        model_portfolio_analytics_service.get_one_day_session_bounds(
            current_datetime
        )
    )

    assert session_start == _utc_datetime(2024, 7, 5, 13, 30)
    assert session_end == _utc_datetime(2024, 7, 5, 20)


def test_get_one_day_session_bounds_before_open_weekday_returns_previous_session(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
) -> None:
    current_datetime = _utc_datetime(2024, 7, 5, 12)

    session_start, session_end = (
        model_portfolio_analytics_service.get_one_day_session_bounds(
            current_datetime
        )
    )

    assert session_start == _utc_datetime(2024, 7, 3, 13, 30)
    assert session_end == _utc_datetime(2024, 7, 3, 17)


def test_get_one_day_session_bounds_holiday_returns_previous_completed_session(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
) -> None:
    current_datetime = _utc_datetime(2024, 7, 4, 16)

    session_start, session_end = (
        model_portfolio_analytics_service.get_one_day_session_bounds(
            current_datetime
        )
    )

    assert session_start == _utc_datetime(2024, 7, 3, 13, 30)
    assert session_end == _utc_datetime(2024, 7, 3, 17)


def test_get_one_day_session_bounds_weekend_returns_previous_completed_session(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
) -> None:
    current_datetime = _utc_datetime(2024, 7, 6, 16)

    session_start, session_end = (
        model_portfolio_analytics_service.get_one_day_session_bounds(
            current_datetime
        )
    )

    assert session_start == _utc_datetime(2024, 7, 5, 13, 30)
    assert session_end == _utc_datetime(2024, 7, 5, 20)


def test_get_one_day_session_bounds_uses_market_date_when_utc_date_differs(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
) -> None:
    current_datetime = _utc_datetime(2024, 7, 6, 1)

    session_start, session_end = (
        model_portfolio_analytics_service.get_one_day_session_bounds(
            current_datetime
        )
    )

    assert session_start == _utc_datetime(2024, 7, 5, 13, 30)
    assert session_end == _utc_datetime(2024, 7, 5, 20)


@pytest.mark.parametrize(
    ("current_datetime", "expected_end"),
    [
        pytest.param(
            _utc_datetime(2024, 7, 5, 13, 30),
            _utc_datetime(2024, 7, 5, 13, 30),
            id="market-open",
        ),
        pytest.param(
            _utc_datetime(2024, 7, 5, 20),
            _utc_datetime(2024, 7, 5, 20),
            id="market-close",
        ),
    ],
)
def test_get_one_day_session_bounds_market_boundaries_are_inclusive(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
    current_datetime: datetime,
    expected_end: datetime,
) -> None:
    session_start, session_end = (
        model_portfolio_analytics_service.get_one_day_session_bounds(
            current_datetime
        )
    )

    assert session_start == _utc_datetime(2024, 7, 5, 13, 30)
    assert session_end == expected_end


def test_get_one_day_session_bounds_respects_early_close_session(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
) -> None:
    current_datetime = _utc_datetime(2024, 7, 3, 18)

    session_start, session_end = (
        model_portfolio_analytics_service.get_one_day_session_bounds(
            current_datetime
        )
    )

    assert session_start == _utc_datetime(2024, 7, 3, 13, 30)
    assert session_end == _utc_datetime(2024, 7, 3, 17)


@pytest.mark.parametrize(
    "current_datetime",
    [
        pytest.param(datetime(2024, 7, 5, 15, 15), id="naive"),
        pytest.param(_market_datetime(2024, 7, 5, 11, 15), id="eastern"),
        pytest.param(
            datetime(
                2024,
                7,
                5,
                8,
                15,
                tzinfo=ZoneInfo("America/Los_Angeles"),
            ),
            id="pacific",
        ),
        pytest.param(
            datetime(
                2024,
                7,
                5,
                17,
                15,
                tzinfo=timezone(timedelta(hours=2)),
            ),
            id="fixed-offset",
        ),
    ],
)
def test_get_one_day_session_bounds_rejects_non_utc_current_datetime(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
    current_datetime: datetime,
) -> None:
    with pytest.raises(ModelPortfolioAnalyticsInternalServerError) as exc_info:
        model_portfolio_analytics_service.get_one_day_session_bounds(
            current_datetime
        )

    assert exc_info.value.code == "MODEL_PORTFOLIO_ANALYTICS_TIMEZONE_REQUIRED"


def test_get_one_day_session_bounds_raises_when_no_usable_session_exists(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
) -> None:
    current_datetime = _utc_datetime(1900, 1, 2, 12)

    with pytest.raises(ModelPortfolioAnalyticsInternalServerError) as exc_info:
        model_portfolio_analytics_service.get_one_day_session_bounds(
            current_datetime
        )

    assert (
        exc_info.value.code
        == "MODEL_PORTFOLIO_ANALYTICS_MARKET_SESSION_NOT_FOUND"
    )


def test_get_analytics_snapshots_returns_empty_when_period_start_is_not_before_current(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
) -> None:
    current_datetime = _utc_datetime(2024, 7, 10, 14)
    snapshots = [
        _snapshot(
            positions=[
                _position(
                    symbol="AAPL",
                    direction=1,
                    leverage=1.0,
                    model_filled_quantity=1.0,
                    model_filled_avg_price=100.0,
                    target_weight=1.0,
                ),
            ],
            timestamp=current_datetime,
        )
    ]

    analytics_snapshots = model_portfolio_analytics_service.get_analytics_snapshots(
        period="1W",
        delta=timedelta(days=7),
        current_datetime=current_datetime,
        model_portfolio_snapshots=snapshots,
        period_start_datetime=current_datetime,
    )

    assert analytics_snapshots == []


def test_get_analytics_snapshots_uses_delta_when_explicit_start_is_missing(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
) -> None:
    current_datetime = _utc_datetime(2024, 7, 10, 14)
    period_start = current_datetime - timedelta(days=7)
    snapshots = [
        _snapshot(
            positions=[
                _position(
                    symbol="AAPL",
                    direction=1,
                    leverage=1.0,
                    model_filled_quantity=1.0,
                    model_filled_avg_price=100.0,
                    target_weight=0.75,
                ),
            ],
            timestamp=period_start,
        ),
        _snapshot(
            positions=[
                _position(
                    symbol="AAPL",
                    direction=1,
                    leverage=1.0,
                    model_filled_quantity=1.0,
                    model_filled_avg_price=100.0,
                    target_weight=0.55,
                ),
            ],
            timestamp=_utc_datetime(2024, 7, 8, 14),
        ),
    ]

    analytics_snapshots = model_portfolio_analytics_service.get_analytics_snapshots(
        period="1W",
        delta=timedelta(days=7),
        current_datetime=current_datetime,
        model_portfolio_snapshots=snapshots,
    )

    assert len(analytics_snapshots) == 2
    assert analytics_snapshots[0].timestamp == period_start
    assert analytics_snapshots[0].positions[0].current_weight == pytest.approx(0.75)
    assert analytics_snapshots[1].timestamp == _utc_datetime(2024, 7, 8, 14)
    assert analytics_snapshots[1].positions[0].current_weight == pytest.approx(0.55)


def test_get_analytics_snapshots_uses_explicit_period_start_over_delta(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
) -> None:
    current_datetime = _utc_datetime(2024, 7, 10, 14)
    explicit_period_start = _utc_datetime(2024, 7, 8, 14)
    snapshots = [
        _snapshot(
            positions=[
                _position(
                    symbol="AAPL",
                    direction=1,
                    leverage=1.0,
                    model_filled_quantity=1.0,
                    model_filled_avg_price=100.0,
                    target_weight=0.25,
                ),
            ],
            timestamp=explicit_period_start,
        ),
    ]

    analytics_snapshots = model_portfolio_analytics_service.get_analytics_snapshots(
        period="1M",
        delta=timedelta(days=30),
        current_datetime=current_datetime,
        model_portfolio_snapshots=snapshots,
        period_start_datetime=explicit_period_start,
    )

    assert len(analytics_snapshots) == 1
    assert analytics_snapshots[0].timestamp == explicit_period_start
    assert analytics_snapshots[0].positions[0].current_weight == pytest.approx(0.25)


def test_get_analytics_snapshots_all_period_starts_at_first_snapshot_minute(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
) -> None:
    first_timestamp = _utc_datetime(2024, 7, 5, 14, 0).replace(
        second=45,
        microsecond=123,
    )
    snapshots = [
        _snapshot(
            positions=[
                _position(
                    symbol="AAPL",
                    direction=1,
                    leverage=1.0,
                    model_filled_quantity=1.0,
                    model_filled_avg_price=100.0,
                    target_weight=0.6,
                ),
                _position(
                    symbol="MSFT",
                    direction=1,
                    leverage=1.0,
                    model_filled_quantity=1.0,
                    model_filled_avg_price=100.0,
                    target_weight=0.4,
                ),
            ],
            timestamp=first_timestamp,
        ),
        _snapshot(
            positions=[
                _position(
                    symbol="AAPL",
                    direction=1,
                    leverage=1.0,
                    model_filled_quantity=1.0,
                    model_filled_avg_price=100.0,
                    target_weight=1.0,
                ),
            ],
            timestamp=_utc_datetime(2024, 7, 8, 14),
        ),
    ]

    analytics_snapshots = model_portfolio_analytics_service.get_analytics_snapshots(
        period="all",
        delta=timedelta(days=365),
        current_datetime=_utc_datetime(2024, 7, 10, 14),
        model_portfolio_snapshots=snapshots,
    )

    assert len(analytics_snapshots) == 2
    assert analytics_snapshots[0].timestamp == _utc_datetime(2024, 7, 5, 14)
    assert analytics_snapshots[0].timestamp.second == 0
    assert analytics_snapshots[0].timestamp.microsecond == 0
    assert {
        position.symbol: position.current_weight
        for position in analytics_snapshots[0].positions
    } == pytest.approx(
        {
            "AAPL": 0.6,
            "MSFT": 0.4,
        }
    )


def test_get_analytics_snapshots_exact_period_start_uses_target_weights(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
) -> None:
    period_start = _utc_datetime(2024, 7, 8, 14)
    snapshots = [
        _snapshot(
            positions=[
                _position(
                    symbol="AAPL",
                    direction=1,
                    leverage=1.0,
                    model_filled_quantity=1.0,
                    model_filled_avg_price=100.0,
                    target_weight=0.7,
                ),
                _position(
                    symbol="MSFT",
                    direction=-1,
                    leverage=1.0,
                    model_filled_quantity=1.0,
                    model_filled_avg_price=100.0,
                    target_weight=0.3,
                ),
            ],
            timestamp=period_start.replace(second=30, microsecond=999),
        )
    ]

    analytics_snapshots = model_portfolio_analytics_service.get_analytics_snapshots(
        period="1W",
        delta=timedelta(days=7),
        current_datetime=_utc_datetime(2024, 7, 10, 14),
        model_portfolio_snapshots=snapshots,
        period_start_datetime=period_start,
    )

    assert len(analytics_snapshots) == 1
    assert analytics_snapshots[0].timestamp == period_start
    assert {
        position.symbol: position.current_weight
        for position in analytics_snapshots[0].positions
    } == pytest.approx(
        {
            "AAPL": 0.7,
            "MSFT": 0.3,
        }
    )


def test_get_analytics_snapshots_lookback_window_counts_weights_and_order(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
    asset_analytics_service: AssetAnalyticsService,
) -> None:
    boundary_source_timestamp = _utc_datetime(2024, 7, 5, 14)
    period_start = _utc_datetime(2024, 7, 8, 14)
    inside_timestamp = _utc_datetime(2024, 7, 9, 14)
    current_datetime = _utc_datetime(2024, 7, 10, 14)
    future_timestamp = _utc_datetime(2024, 7, 11, 14)
    boundary_symbols = ["AAPL", "MSFT"]
    boundary_start_prices_df = asset_analytics_service.get_prices_at_time(
        symbols=boundary_symbols,
        timestamp=boundary_source_timestamp,
    )
    boundary_start_prices = {
        str(symbol): float(price)
        for symbol, price in boundary_start_prices_df.set_index("symbol")["price"]
        .to_dict()
        .items()
    }
    boundary_end_prices_df = asset_analytics_service.get_prices_at_time(
        symbols=boundary_symbols,
        timestamp=period_start,
    )
    boundary_end_prices = {
        str(symbol): float(price)
        for symbol, price in boundary_end_prices_df.set_index("symbol")["price"]
        .to_dict()
        .items()
    }
    boundary_source_snapshot = _snapshot(
        positions=[
            _position(
                symbol="AAPL",
                direction=1,
                leverage=1.0,
                model_filled_quantity=5.0,
                model_filled_avg_price=boundary_start_prices["AAPL"],
                target_weight=0.8,
            ),
            _position(
                symbol="MSFT",
                direction=-1,
                leverage=1.5,
                model_filled_quantity=2.0,
                model_filled_avg_price=boundary_start_prices["MSFT"],
                target_weight=0.2,
            ),
        ],
        timestamp=boundary_source_timestamp,
    )
    inside_snapshot = _snapshot(
        positions=[
            _position(
                symbol="AAPL",
                direction=1,
                leverage=1.0,
                model_filled_quantity=1.0,
                model_filled_avg_price=100.0,
                target_weight=0.55,
            ),
            _position(
                symbol="GOOG",
                direction=1,
                leverage=2.0,
                model_filled_quantity=1.0,
                model_filled_avg_price=100.0,
                target_weight=0.45,
            ),
        ],
        timestamp=inside_timestamp,
    )
    current_snapshot = _snapshot(
        positions=[
            _position(
                symbol="NVDA",
                direction=1,
                leverage=1.0,
                model_filled_quantity=1.0,
                model_filled_avg_price=100.0,
                target_weight=1.0,
            ),
        ],
        timestamp=current_datetime,
    )
    future_snapshot = _snapshot(
        positions=[
            _position(
                symbol="TSLA",
                direction=1,
                leverage=1.0,
                model_filled_quantity=1.0,
                model_filled_avg_price=100.0,
                target_weight=1.0,
            ),
        ],
        timestamp=future_timestamp,
    )

    analytics_snapshots = model_portfolio_analytics_service.get_analytics_snapshots(
        period="1W",
        delta=timedelta(days=7),
        current_datetime=current_datetime,
        model_portfolio_snapshots=[
            boundary_source_snapshot,
            inside_snapshot,
            current_snapshot,
            future_snapshot,
        ],
        period_start_datetime=period_start,
    )

    assert len(analytics_snapshots) == 3
    assert [snapshot.timestamp for snapshot in analytics_snapshots] == [
        period_start,
        inside_timestamp,
        current_datetime,
    ]
    assert [snapshot.timestamp for snapshot in analytics_snapshots] == sorted(
        snapshot.timestamp for snapshot in analytics_snapshots
    )
    assert {
        position.symbol: position.current_weight
        for position in analytics_snapshots[0].positions
    } == pytest.approx(
        _expected_updated_weights(
            snapshot=boundary_source_snapshot,
            start_prices=boundary_start_prices,
            end_prices=boundary_end_prices,
        )
    )
    assert {
        position.symbol: position.current_weight
        for position in analytics_snapshots[1].positions
    } == pytest.approx(
        {
            "AAPL": 0.55,
            "GOOG": 0.45,
        }
    )
    assert {
        position.symbol: position.current_weight
        for position in analytics_snapshots[2].positions
    } == pytest.approx({"NVDA": 1.0})


def test_get_stock_prices_at_snapshot_changes_no_snapshots_leaves_prices_unchanged(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
) -> None:
    existing_timestamp = _utc_datetime(2024, 7, 1, 14)
    segment_prices = pd.DataFrame(
        data={"AAPL": [123.45]},
        index=pd.DatetimeIndex([existing_timestamp]),
    )
    expected_prices = segment_prices.copy(deep=True)

    model_portfolio_analytics_service.get_stock_prices_at_snapshot_changes(
        segment_prices=segment_prices,
        analytics_snapshots=[],
    )

    assert segment_prices.equals(expected_prices)


def test_get_stock_prices_at_snapshot_changes_single_snapshot_inserts_prices(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
    asset_analytics_service: AssetAnalyticsService,
) -> None:
    timestamp = _utc_datetime(2024, 7, 5, 14)
    symbols = ["AAPL", "MSFT", "GOOG"]
    segment_prices = pd.DataFrame()
    analytics_snapshots = [
        _analytics_snapshot(
            symbols=symbols,
            timestamp=timestamp,
        ),
    ]

    model_portfolio_analytics_service.get_stock_prices_at_snapshot_changes(
        segment_prices=segment_prices,
        analytics_snapshots=analytics_snapshots,
    )
    expected_prices_df = asset_analytics_service.get_prices_at_time(
        symbols=sorted(symbols),
        timestamp=timestamp,
    )

    assert segment_prices.index.name == "timestamp"
    assert segment_prices.index.is_monotonic_increasing
    for price_row in expected_prices_df.itertuples(index=False):
        assert price_row.timestamp in segment_prices.index
        assert segment_prices.loc[
            price_row.timestamp,
            price_row.symbol,
        ] == pytest.approx(price_row.price)


def test_get_stock_prices_at_snapshot_changes_same_symbols_adds_transition_row(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
    asset_analytics_service: AssetAnalyticsService,
) -> None:
    first_timestamp = _utc_datetime(2024, 7, 5, 14)
    second_timestamp = _utc_datetime(2024, 7, 8, 14)
    symbols = ["AAPL", "MSFT"]
    segment_prices = pd.DataFrame()
    analytics_snapshots = [
        _analytics_snapshot(symbols=symbols, timestamp=first_timestamp),
        _analytics_snapshot(symbols=symbols, timestamp=second_timestamp),
    ]

    model_portfolio_analytics_service.get_stock_prices_at_snapshot_changes(
        segment_prices=segment_prices,
        analytics_snapshots=analytics_snapshots,
    )
    first_expected_prices_df = asset_analytics_service.get_prices_at_time(
        symbols=sorted(symbols),
        timestamp=first_timestamp,
    )
    second_expected_prices_df = asset_analytics_service.get_prices_at_time(
        symbols=sorted(symbols),
        timestamp=second_timestamp,
    )

    assert len(segment_prices.index) == 2
    for expected_prices_df in [first_expected_prices_df, second_expected_prices_df]:
        for price_row in expected_prices_df.itertuples(index=False):
            assert price_row.timestamp in segment_prices.index
            assert segment_prices.loc[
                price_row.timestamp,
                price_row.symbol,
            ] == pytest.approx(price_row.price)


def test_get_stock_prices_at_snapshot_changes_changed_symbols_uses_transition_union(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
    asset_analytics_service: AssetAnalyticsService,
) -> None:
    first_timestamp = _utc_datetime(2024, 7, 5, 14)
    second_timestamp = _utc_datetime(2024, 7, 8, 14)
    segment_prices = pd.DataFrame()
    analytics_snapshots = [
        _analytics_snapshot(symbols=["AAPL", "MSFT"], timestamp=first_timestamp),
        _analytics_snapshot(symbols=["MSFT", "GOOG"], timestamp=second_timestamp),
    ]

    model_portfolio_analytics_service.get_stock_prices_at_snapshot_changes(
        segment_prices=segment_prices,
        analytics_snapshots=analytics_snapshots,
    )
    first_expected_prices_df = asset_analytics_service.get_prices_at_time(
        symbols=["AAPL", "MSFT"],
        timestamp=first_timestamp,
    )
    transition_expected_prices_df = asset_analytics_service.get_prices_at_time(
        symbols=["AAPL", "GOOG", "MSFT"],
        timestamp=second_timestamp,
    )

    for price_row in first_expected_prices_df.itertuples(index=False):
        assert price_row.timestamp in segment_prices.index
        assert segment_prices.loc[
            price_row.timestamp,
            price_row.symbol,
        ] == pytest.approx(price_row.price)
    for price_row in transition_expected_prices_df.itertuples(index=False):
        assert price_row.timestamp in segment_prices.index
        assert segment_prices.loc[
            price_row.timestamp,
            price_row.symbol,
        ] == pytest.approx(price_row.price)


def test_get_stock_prices_at_snapshot_changes_multiple_transitions(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
    asset_analytics_service: AssetAnalyticsService,
) -> None:
    first_timestamp = _utc_datetime(2024, 7, 5, 14)
    second_timestamp = _utc_datetime(2024, 7, 8, 14)
    third_timestamp = _utc_datetime(2024, 7, 9, 14)
    segment_prices = pd.DataFrame()
    analytics_snapshots = [
        _analytics_snapshot(symbols=["AAPL"], timestamp=first_timestamp),
        _analytics_snapshot(symbols=["AAPL", "MSFT"], timestamp=second_timestamp),
        _analytics_snapshot(symbols=["GOOG"], timestamp=third_timestamp),
    ]

    model_portfolio_analytics_service.get_stock_prices_at_snapshot_changes(
        segment_prices=segment_prices,
        analytics_snapshots=analytics_snapshots,
    )
    first_expected_prices_df = asset_analytics_service.get_prices_at_time(
        symbols=["AAPL"],
        timestamp=first_timestamp,
    )
    second_expected_prices_df = asset_analytics_service.get_prices_at_time(
        symbols=["AAPL", "MSFT"],
        timestamp=second_timestamp,
    )
    third_expected_prices_df = asset_analytics_service.get_prices_at_time(
        symbols=["AAPL", "GOOG", "MSFT"],
        timestamp=third_timestamp,
    )

    assert len(segment_prices.index) == 3
    for expected_prices_df in [
        first_expected_prices_df,
        second_expected_prices_df,
        third_expected_prices_df,
    ]:
        for price_row in expected_prices_df.itertuples(index=False):
            assert price_row.timestamp in segment_prices.index
            assert segment_prices.loc[
                price_row.timestamp,
                price_row.symbol,
            ] == pytest.approx(price_row.price)


def test_get_stock_prices_at_snapshot_changes_preserves_existing_prices_and_sorts(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
    asset_analytics_service: AssetAnalyticsService,
) -> None:
    existing_timestamp = _utc_datetime(2024, 7, 10, 14)
    snapshot_timestamp = _utc_datetime(2024, 7, 5, 14)
    segment_prices = pd.DataFrame(
        data={"AAPL": [123.45]},
        index=pd.DatetimeIndex([existing_timestamp]),
    )
    analytics_snapshots = [
        _analytics_snapshot(symbols=["MSFT", "GOOG"], timestamp=snapshot_timestamp),
    ]

    model_portfolio_analytics_service.get_stock_prices_at_snapshot_changes(
        segment_prices=segment_prices,
        analytics_snapshots=analytics_snapshots,
    )
    expected_prices_df = asset_analytics_service.get_prices_at_time(
        symbols=["GOOG", "MSFT"],
        timestamp=snapshot_timestamp,
    )

    assert segment_prices.index.name == "timestamp"
    assert segment_prices.index.is_monotonic_increasing
    assert segment_prices.loc[existing_timestamp, "AAPL"] == pytest.approx(123.45)
    for price_row in expected_prices_df.itertuples(index=False):
        assert price_row.timestamp in segment_prices.index
        assert segment_prices.loc[
            price_row.timestamp,
            price_row.symbol,
        ] == pytest.approx(price_row.price)


def test_get_positions_updated_weights_mixed_long_and_short_positions(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
    asset_analytics_service: AssetAnalyticsService,
) -> None:
    start_datetime = _utc_datetime(2024, 7, 5, 14)
    end_datetime = _utc_datetime(2024, 7, 5, 19)
    symbols = ["AAPL", "MSFT", "GOOG"]
    start_prices_df = asset_analytics_service.get_prices_at_time(
        symbols=symbols,
        timestamp=start_datetime,
    )
    start_prices = {
        str(symbol): float(price)
        for symbol, price in start_prices_df.set_index("symbol")["price"]
        .to_dict()
        .items()
    }
    snapshot = _snapshot(
        positions=[
            _position(
                symbol="AAPL",
                direction=1,
                leverage=1.0,
                model_filled_quantity=10.0,
                model_filled_avg_price=start_prices["AAPL"],
            ),
            _position(
                symbol="MSFT",
                direction=-1,
                leverage=1.5,
                model_filled_quantity=4.0,
                model_filled_avg_price=start_prices["MSFT"],
            ),
            _position(
                symbol="GOOG",
                direction=1,
                leverage=2.0,
                model_filled_quantity=3.0,
                model_filled_avg_price=start_prices["GOOG"],
            ),
        ],
    )
    weights = model_portfolio_analytics_service.get_positions_updated_weights(
        model_porfolio_snapshot=snapshot,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
    )
    end_prices_df = asset_analytics_service.get_prices_at_time(
        symbols=symbols,
        timestamp=end_datetime,
    )
    end_prices = {
        str(symbol): float(price)
        for symbol, price in end_prices_df.set_index("symbol")["price"]
        .to_dict()
        .items()
    }

    assert weights == pytest.approx(
        _expected_updated_weights(
            snapshot=snapshot,
            start_prices=start_prices,
            end_prices=end_prices,
        )
    )


def test_get_positions_updated_weights_long_only_positions(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
    asset_analytics_service: AssetAnalyticsService,
) -> None:
    start_datetime = _utc_datetime(2024, 7, 8, 14)
    end_datetime = _utc_datetime(2024, 7, 9, 19)
    symbols = ["AAPL", "NVDA", "GOOG"]
    start_prices_df = asset_analytics_service.get_prices_at_time(
        symbols=symbols,
        timestamp=start_datetime,
    )
    start_prices = {
        str(symbol): float(price)
        for symbol, price in start_prices_df.set_index("symbol")["price"]
        .to_dict()
        .items()
    }
    snapshot = _snapshot(
        positions=[
            _position(
                symbol="AAPL",
                direction=1,
                leverage=1.0,
                model_filled_quantity=5.0,
                model_filled_avg_price=start_prices["AAPL"],
            ),
            _position(
                symbol="NVDA",
                direction=1,
                leverage=2.0,
                model_filled_quantity=6.0,
                model_filled_avg_price=start_prices["NVDA"],
            ),
            _position(
                symbol="GOOG",
                direction=1,
                leverage=1.5,
                model_filled_quantity=4.0,
                model_filled_avg_price=start_prices["GOOG"],
            ),
        ],
    )
    weights = model_portfolio_analytics_service.get_positions_updated_weights(
        model_porfolio_snapshot=snapshot,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
    )
    end_prices_df = asset_analytics_service.get_prices_at_time(
        symbols=symbols,
        timestamp=end_datetime,
    )
    end_prices = {
        str(symbol): float(price)
        for symbol, price in end_prices_df.set_index("symbol")["price"]
        .to_dict()
        .items()
    }

    assert weights == pytest.approx(
        _expected_updated_weights(
            snapshot=snapshot,
            start_prices=start_prices,
            end_prices=end_prices,
        )
    )


def test_get_positions_updated_weights_short_only_positions(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
    asset_analytics_service: AssetAnalyticsService,
) -> None:
    start_datetime = _utc_datetime(2024, 7, 10, 14)
    end_datetime = _utc_datetime(2024, 7, 11, 19)
    symbols = ["META", "NFLX", "AMD"]
    start_prices_df = asset_analytics_service.get_prices_at_time(
        symbols=symbols,
        timestamp=start_datetime,
    )
    start_prices = {
        str(symbol): float(price)
        for symbol, price in start_prices_df.set_index("symbol")["price"]
        .to_dict()
        .items()
    }
    snapshot = _snapshot(
        positions=[
            _position(
                symbol="META",
                direction=-1,
                leverage=1.0,
                model_filled_quantity=2.0,
                model_filled_avg_price=start_prices["META"],
            ),
            _position(
                symbol="NFLX",
                direction=-1,
                leverage=1.5,
                model_filled_quantity=1.0,
                model_filled_avg_price=start_prices["NFLX"],
            ),
            _position(
                symbol="AMD",
                direction=-1,
                leverage=2.0,
                model_filled_quantity=8.0,
                model_filled_avg_price=start_prices["AMD"],
            ),
        ],
    )
    weights = model_portfolio_analytics_service.get_positions_updated_weights(
        model_porfolio_snapshot=snapshot,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
    )
    end_prices_df = asset_analytics_service.get_prices_at_time(
        symbols=symbols,
        timestamp=end_datetime,
    )
    end_prices = {
        str(symbol): float(price)
        for symbol, price in end_prices_df.set_index("symbol")["price"]
        .to_dict()
        .items()
    }

    assert weights == pytest.approx(
        _expected_updated_weights(
            snapshot=snapshot,
            start_prices=start_prices,
            end_prices=end_prices,
        )
    )


def test_get_model_portfolio_bars_returns_empty_when_portfolio_has_no_snapshots(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    portfolio_id: str | None = None
    try:
        portfolio_id = _persist_raw_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=test_user_1.cognito_user_id,
            snapshots=[],
        )

        response = model_portfolio_analytics_service.get_model_portfolio_bars(
            portfolio_id=portfolio_id,
            current_datetime=_utc_datetime(2024, 7, 10, 15, 30),
        )

        assert response == {}
    finally:
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            portfolio_id=portfolio_id,
        )


def test_get_model_portfolio_bars_returns_default_periods_with_valid_metrics(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    current_datetime = _utc_datetime(2024, 7, 10, 15, 30)
    expected_timeframes = {
        "1D": "5Min",
        "1W": "1H",
        "1M": "1D",
        "3M": "1D",
        "1A": "1D",
        "all": "1D",
    }
    portfolio_id: str | None = None
    try:
        portfolio_id = _persist_bars_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=test_user_1.cognito_user_id,
        )

        response = model_portfolio_analytics_service.get_model_portfolio_bars(
            portfolio_id=portfolio_id,
            current_datetime=current_datetime,
        )

        assert set(response) == set(expected_timeframes)
        session_start, session_end = (
            model_portfolio_analytics_service.get_one_day_session_bounds(
                current_datetime
            )
        )
        for period, expected_timeframe in expected_timeframes.items():
            period_response = response[period]
            _assert_period_payload_is_valid(
                period_response=period_response,
                expected_timeframe=expected_timeframe,
            )
            assert period_response["timestamp"][-1] <= current_datetime

        assert response["1D"]["timestamp"][0] >= session_start
        assert response["1D"]["timestamp"][-1] <= session_end
        assert response["1D"]["timestamp"][0] != current_datetime - timedelta(days=1)
        assert response["1W"]["timestamp"][0] >= current_datetime - timedelta(weeks=1)
        assert response["1M"]["timestamp"][0] >= current_datetime - timedelta(days=30)
        assert response["3M"]["timestamp"][0] >= current_datetime - timedelta(days=90)
        assert response["1A"]["timestamp"][0] >= current_datetime - timedelta(days=365)
        assert response["all"]["timestamp"][0] == _utc_datetime(2023, 7, 3, 14)
    finally:
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            portfolio_id=portfolio_id,
        )


def test_get_model_portfolio_bars_one_day_after_hours_uses_completed_session(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    current_datetime = _utc_datetime(2024, 7, 10, 22)
    portfolio_id: str | None = None
    try:
        portfolio_id = _persist_bars_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=test_user_1.cognito_user_id,
        )

        response = model_portfolio_analytics_service.get_model_portfolio_bars(
            portfolio_id=portfolio_id,
            current_datetime=current_datetime,
        )

        assert "1D" in response
        _assert_period_payload_is_valid(
            period_response=response["1D"],
            expected_timeframe="5Min",
        )
        assert response["1D"]["timestamp"][0] >= _utc_datetime(2024, 7, 10, 13, 30)
        assert response["1D"]["timestamp"][-1] <= _utc_datetime(2024, 7, 10, 20)
    finally:
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            portfolio_id=portfolio_id,
        )


def test_get_model_portfolio_bars_sorts_history_and_stitches_rebalance_changes(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    current_datetime = _utc_datetime(2024, 7, 10, 15, 30)
    latest_snapshot = _raw_snapshot(
        timestamp=_utc_datetime(2024, 7, 9, 14),
        positions=[
            _raw_position(
                symbol="MSFT",
                target_weight=0.3,
                direction=1,
                leverage=1.0,
                model_filled_quantity=7.0,
                model_filled_avg_price=460.0,
            ),
            _raw_position(
                symbol="GOOG",
                target_weight=0.7,
                direction=-1,
                leverage=1.0,
                model_filled_quantity=20.0,
                model_filled_avg_price=190.0,
            ),
        ],
    )
    first_snapshot = _raw_snapshot(
        timestamp=_utc_datetime(2023, 7, 3, 14),
        positions=[
            _raw_position(
                symbol="AAPL",
                target_weight=0.5,
                direction=1,
                leverage=1.0,
                model_filled_quantity=25.0,
                model_filled_avg_price=192.0,
            ),
            _raw_position(
                symbol="MSFT",
                target_weight=0.5,
                direction=-1,
                leverage=1.0,
                model_filled_quantity=11.0,
                model_filled_avg_price=338.0,
            ),
        ],
    )
    middle_snapshot = _raw_snapshot(
        timestamp=_utc_datetime(2024, 6, 10, 14),
        positions=[
            _raw_position(
                symbol="AAPL",
                target_weight=0.4,
                direction=1,
                leverage=1.0,
                model_filled_quantity=18.0,
                model_filled_avg_price=193.0,
            ),
            _raw_position(
                symbol="GOOG",
                target_weight=0.6,
                direction=1,
                leverage=1.0,
                model_filled_quantity=25.0,
                model_filled_avg_price=176.0,
            ),
        ],
    )
    portfolio_id: str | None = None
    try:
        portfolio_id = _persist_bars_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=test_user_1.cognito_user_id,
            snapshots=[latest_snapshot, first_snapshot, middle_snapshot],
        )

        response = model_portfolio_analytics_service.get_model_portfolio_bars(
            portfolio_id=portfolio_id,
            current_datetime=current_datetime,
        )

        assert set(response) == {"1D", "1W", "1M", "3M", "1A", "all"}
        for period_response in response.values():
            assert period_response["timestamp"] == sorted(
                period_response["timestamp"]
            )
            assert len(period_response["timestamp"]) == len(
                set(period_response["timestamp"])
            )
            assert len(period_response["timestamp"]) == len(
                period_response["cumulative_returns"]
            )
        assert response["all"]["timestamp"][0] == _utc_datetime(2023, 7, 3, 14)
    finally:
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            portfolio_id=portfolio_id,
        )


def test_get_model_portfolio_bars_omits_periods_with_no_usable_snapshots(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    portfolio_id: str | None = None
    try:
        portfolio_id = _persist_bars_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=test_user_1.cognito_user_id,
            snapshots=[
                _raw_snapshot(
                    timestamp=_utc_datetime(2024, 7, 12, 14),
                    positions=[
                        _raw_position(
                            symbol="AAPL",
                            target_weight=1.0,
                            direction=1,
                            leverage=1.0,
                            model_filled_quantity=50.0,
                            model_filled_avg_price=230.0,
                        ),
                    ],
                ),
            ],
        )

        response = model_portfolio_analytics_service.get_model_portfolio_bars(
            portfolio_id=portfolio_id,
            current_datetime=_utc_datetime(2024, 7, 10, 15, 30),
        )

        assert response == {}
    finally:
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            portfolio_id=portfolio_id,
        )


def test_calculate_model_portfolio_period_omits_when_no_trading_time_elapsed(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
) -> None:
    snapshot = ModelPortfolioSnapshot(
        snapshot_id=f"snapshot-{uuid4()}",
        timestamp=_utc_datetime(2024, 7, 13, 13),
        positions=[
            ModelPortfolioPosition(
                symbol="AAPL",
                target_weight=1.0,
                direction=1,
                leverage=1.0,
                model_filled_quantity=10.0,
                model_filled_avg_price=230.0,
            )
        ],
    )

    period, payload = (
        model_portfolio_analytics_service._calculate_model_portfolio_period(
            portfolio_id=f"tests-v2-no-trading-time-{uuid4()}",
            current_datetime=_utc_datetime(2024, 7, 13, 14),
            model_portfolio_snapshots=[snapshot],
            period="1W",
            delta=timedelta(hours=1),
            timeframe="1H",
        )
    )

    assert period == "1W"
    assert payload is None


def test_calculate_model_portfolio_period_raises_when_trading_time_elapsed_without_analytics(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
) -> None:
    snapshot = ModelPortfolioSnapshot(
        snapshot_id=f"snapshot-{uuid4()}",
        timestamp=_utc_datetime(2024, 7, 12, 14),
        positions=[
            ModelPortfolioPosition(
                symbol="AAPL",
                target_weight=1.0,
                direction=1,
                leverage=1.0,
                model_filled_quantity=10.0,
                model_filled_avg_price=230.0,
            )
        ],
    )

    with pytest.raises(ModelPortfolioAnalyticsInternalServerError) as exc_info:
        model_portfolio_analytics_service._calculate_model_portfolio_period(
            portfolio_id=f"tests-v2-trading-time-no-analytics-{uuid4()}",
            current_datetime=_utc_datetime(2024, 7, 12, 14, 1),
            model_portfolio_snapshots=[snapshot],
            period="1W",
            delta=timedelta(minutes=1),
            timeframe="1H",
        )

    assert (
        exc_info.value.code
        == "MODEL_PORTFOLIO_ANALYTICS_BENCHMARK_ALIGNED_PRICE_DATA_MISSING"
    )


@pytest.mark.parametrize(
    "current_datetime",
    [
        pytest.param(datetime(2024, 7, 10, 15, 30), id="naive"),
        pytest.param(_market_datetime(2024, 7, 10, 11, 30), id="eastern"),
    ],
)
def test_get_model_portfolio_bars_rejects_non_utc_current_datetime(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
    current_datetime: datetime,
) -> None:
    portfolio_id: str | None = None
    try:
        portfolio_id = _persist_bars_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=test_user_1.cognito_user_id,
        )

        with pytest.raises(ModelPortfolioAnalyticsInternalServerError) as exc_info:
            model_portfolio_analytics_service.get_model_portfolio_bars(
                portfolio_id=portfolio_id,
                current_datetime=current_datetime,
            )

        assert (
            exc_info.value.code
            == "MODEL_PORTFOLIO_ANALYTICS_TIMEZONE_REQUIRED"
        )
    finally:
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            portfolio_id=portfolio_id,
        )


def test_get_model_portfolio_bars_raises_for_natural_invalid_symbol_failure(
    model_portfolio_analytics_service: ModelPortfolioAnalyticsService,
    model_portfolio_repository: ModelPortfolioRepository,
    test_user_1,
) -> None:
    portfolio_id: str | None = None
    try:
        portfolio_id = _persist_bars_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            owner_cognito_user_id=test_user_1.cognito_user_id,
            snapshots=[
                _raw_snapshot(
                    timestamp=_utc_datetime(2024, 7, 9, 14),
                    positions=[
                        _raw_position(
                            symbol=f"ZZZNOTREAL{uuid4().hex[:8].upper()}",
                            target_weight=1.0,
                            direction=1,
                            leverage=1.0,
                            model_filled_quantity=1.0,
                            model_filled_avg_price=1.0,
                        ),
                    ],
                ),
            ],
        )

        with pytest.raises(ModelPortfolioAnalyticsInternalServerError):
            model_portfolio_analytics_service.get_model_portfolio_bars(
                portfolio_id=portfolio_id,
                current_datetime=_utc_datetime(2024, 7, 10, 15, 30),
            )
    finally:
        _delete_model_portfolio(
            model_portfolio_repository=model_portfolio_repository,
            portfolio_id=portfolio_id,
        )
