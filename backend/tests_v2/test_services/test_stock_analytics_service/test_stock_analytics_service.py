from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from services.stock_analytics_service import (
    StockAnalyticsInternalServerError,
    StockAnalyticsService,
)


"""
These tests exercise StockAnalyticsService with fully integrated dependencies.

Coverage goals:
- get_one_day_session_bounds(): resolve active trading day, after-hours weekday,
  before-open weekday, holiday, weekend, UTC-date/market-date mismatch, exact
  market open/close, and early-close sessions through the real market calendar.
- get_one_day_session_bounds(): reject naive, Eastern, Pacific, and fixed-offset
  non-UTC current_datetime values before calendar lookup.
- get_earliest_price_datetime(): fetch real yfinance daily history for a stock,
  return the first available UTC-aware timestamp, reject non-UTC current_datetime,
  and raise naturally for symbols with no usable history.
- _calculate_stock_period(): calculate real 1D, 1W, 1M, 3M, 1A, and all-time
  periods through the real market-data and analytics stack; verify usable payload
  shape, UTC timestamps, prices, timeframe mapping, metric fields, and period
  omission when the earliest price timestamp leaves no usable window.
- get_stock_analytics_by_periods(): return the default 1D, 1W, 1M, 3M, 1A, and all periods for
  a real stock with expected timeframes, ordered keys, UTC timestamps, aligned
  prices, and metric fields; filter to requested periods; use
  datetime.now(timezone.utc) when current_datetime is omitted; immediately reject
  non-UTC current_datetime; and raise naturally for invalid symbols.
- get_stock_analytics_by_periods(): use a recently IPO'd stock to verify the 1A period still
  works when the stock's earliest available price is inside the one-year
  lookback window.

Not covered here because they require a mock or controlled lower-level resource:
missing stock/SPY columns, empty/all-null provider DataFrames for otherwise valid
symbols, price lookup failures, analytics calculation failures, duplicate rows,
and forced period-start seed-row insertion.
"""


pytestmark = pytest.mark.integration

MARKET_TIMEZONE = ZoneInfo("America/New_York")
METRIC_FIELDS = {
    "final_cumulative_return",
    "cagr",
    "annualized_volatility",
    "leverage_adjusted_direction",
    "alpha",
    "beta",
    "sharpe_ratio",
    "maximum_drawdown",
    "maximum_drawdown_duration",
}
DEFAULT_PERIOD_TIMEFRAMES = {
    "all": "1D",
    "1D": "5Min",
    "1W": "1H",
    "1M": "1D",
    "3M": "1D",
    "1A": "1D",
}


def _utc_datetime(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int = 0,
) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _market_datetime(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int = 0,
) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=MARKET_TIMEZONE)


def _assert_metric_is_valid(value: float | int | None) -> None:
    assert value is None or isinstance(value, (int, float))
    if isinstance(value, (int, float)):
        assert math.isfinite(float(value))


def _assert_period_payload_is_valid(
    payload: dict,
    *,
    expected_timeframe: str,
) -> None:
    assert set(payload) >= {"timeframe", "timestamp", "prices", *METRIC_FIELDS}
    assert payload["timeframe"] == expected_timeframe
    assert len(payload["timestamp"]) == len(payload["prices"])
    assert payload["timestamp"]
    assert payload["prices"]
    assert payload["timestamp"] == sorted(payload["timestamp"])

    for timestamp in payload["timestamp"]:
        assert timestamp.tzinfo is not None
        assert timestamp.utcoffset() == timedelta(0)
    for price in payload["prices"]:
        assert isinstance(price, float)
        assert math.isfinite(price)
        assert price > 0.0
    for field in METRIC_FIELDS:
        _assert_metric_is_valid(payload[field])


def test_get_one_day_session_bounds_active_trading_day_ends_at_current_time(
    stock_analytics_service: StockAnalyticsService,
) -> None:
    current_datetime = _utc_datetime(2024, 7, 5, 15, 0)

    session_open, session_close = (
        stock_analytics_service.get_one_day_session_bounds(current_datetime)
    )

    assert session_open == _utc_datetime(2024, 7, 5, 13, 30)
    assert session_close == current_datetime


def test_get_one_day_session_bounds_after_hours_weekday_returns_completed_session(
    stock_analytics_service: StockAnalyticsService,
) -> None:
    session_open, session_close = stock_analytics_service.get_one_day_session_bounds(
        _utc_datetime(2024, 7, 5, 21, 0)
    )

    assert session_open == _utc_datetime(2024, 7, 5, 13, 30)
    assert session_close == _utc_datetime(2024, 7, 5, 20, 0)


def test_get_one_day_session_bounds_before_open_weekday_returns_previous_session(
    stock_analytics_service: StockAnalyticsService,
) -> None:
    session_open, session_close = stock_analytics_service.get_one_day_session_bounds(
        _utc_datetime(2024, 7, 5, 12, 0)
    )

    assert session_open == _utc_datetime(2024, 7, 3, 13, 30)
    assert session_close == _utc_datetime(2024, 7, 3, 17, 0)


def test_get_one_day_session_bounds_holiday_returns_previous_completed_session(
    stock_analytics_service: StockAnalyticsService,
) -> None:
    session_open, session_close = stock_analytics_service.get_one_day_session_bounds(
        _utc_datetime(2024, 7, 4, 16, 0)
    )

    assert session_open == _utc_datetime(2024, 7, 3, 13, 30)
    assert session_close == _utc_datetime(2024, 7, 3, 17, 0)


def test_get_one_day_session_bounds_weekend_returns_previous_completed_session(
    stock_analytics_service: StockAnalyticsService,
) -> None:
    session_open, session_close = stock_analytics_service.get_one_day_session_bounds(
        _utc_datetime(2024, 7, 7, 16, 0)
    )

    assert session_open == _utc_datetime(2024, 7, 5, 13, 30)
    assert session_close == _utc_datetime(2024, 7, 5, 20, 0)


def test_get_one_day_session_bounds_uses_market_date_when_utc_date_differs(
    stock_analytics_service: StockAnalyticsService,
) -> None:
    current_datetime = _utc_datetime(2024, 7, 6, 0, 30)

    session_open, session_close = (
        stock_analytics_service.get_one_day_session_bounds(current_datetime)
    )

    assert session_open == _utc_datetime(2024, 7, 5, 13, 30)
    assert session_close == _utc_datetime(2024, 7, 5, 20, 0)


@pytest.mark.parametrize(
    ("current_datetime", "expected_close"),
    [
        (_utc_datetime(2024, 7, 5, 13, 30), _utc_datetime(2024, 7, 5, 13, 30)),
        (_utc_datetime(2024, 7, 5, 20, 0), _utc_datetime(2024, 7, 5, 20, 0)),
    ],
)
def test_get_one_day_session_bounds_market_boundaries_are_inclusive(
    current_datetime: datetime,
    expected_close: datetime,
    stock_analytics_service: StockAnalyticsService,
) -> None:
    session_open, session_close = (
        stock_analytics_service.get_one_day_session_bounds(current_datetime)
    )

    assert session_open == _utc_datetime(2024, 7, 5, 13, 30)
    assert session_close == expected_close


def test_get_one_day_session_bounds_respects_early_close_session(
    stock_analytics_service: StockAnalyticsService,
) -> None:
    session_open, session_close = stock_analytics_service.get_one_day_session_bounds(
        _utc_datetime(2024, 11, 29, 20, 0)
    )

    assert session_open == _utc_datetime(2024, 11, 29, 14, 30)
    assert session_close == _utc_datetime(2024, 11, 29, 18, 0)


@pytest.mark.parametrize(
    "current_datetime",
    [
        datetime(2024, 7, 5, 15, 0),
        _market_datetime(2024, 7, 5, 11, 0),
        datetime(2024, 7, 5, 8, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
        datetime(2024, 7, 5, 16, 0, tzinfo=timezone(timedelta(hours=1))),
    ],
)
def test_get_one_day_session_bounds_rejects_non_utc_current_datetime(
    current_datetime: datetime,
    stock_analytics_service: StockAnalyticsService,
) -> None:
    with pytest.raises(StockAnalyticsInternalServerError) as error:
        stock_analytics_service.get_one_day_session_bounds(current_datetime)

    assert error.value.code == "STOCK_ANALYTICS_TIMEZONE_REQUIRED"


def test_get_earliest_price_datetime_returns_first_utc_price(
    stock_analytics_service: StockAnalyticsService,
) -> None:
    current_datetime = _utc_datetime(2024, 7, 5, 20, 0)

    earliest = stock_analytics_service.get_earliest_price_datetime(
        symbol="AAPL",
        current_datetime=current_datetime,
    )

    assert earliest.tzinfo is not None
    assert earliest.utcoffset() == timedelta(0)
    assert earliest < current_datetime
    assert earliest.date().year < 2024


@pytest.mark.parametrize(
    "current_datetime",
    [
        datetime(2024, 1, 5, 21, 0),
        _market_datetime(2024, 1, 5, 16, 0),
        datetime(2024, 1, 5, 13, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
        datetime(2024, 1, 5, 22, 0, tzinfo=timezone(timedelta(hours=1))),
    ],
)
def test_get_earliest_price_datetime_rejects_non_utc_current_datetime(
    current_datetime: datetime,
    stock_analytics_service: StockAnalyticsService,
) -> None:
    with pytest.raises(StockAnalyticsInternalServerError) as error:
        stock_analytics_service.get_earliest_price_datetime(
            symbol="AAPL",
            current_datetime=current_datetime,
        )

    assert error.value.code == "STOCK_ANALYTICS_TIMEZONE_REQUIRED"


def test_get_earliest_price_datetime_raises_for_natural_invalid_symbol_failure(
    stock_analytics_service: StockAnalyticsService,
) -> None:
    with pytest.raises(StockAnalyticsInternalServerError) as error:
        stock_analytics_service.get_earliest_price_datetime(
            symbol="NOTAREALBASKTSTOCK",
            current_datetime=_utc_datetime(2024, 7, 5, 20, 0),
        )

    assert error.value.code in {
        "STOCK_ANALYTICS_EARLIEST_PRICE_LOOKUP_FAILED",
        "STOCK_ANALYTICS_PRICE_HISTORY_MISSING",
    }


@pytest.mark.parametrize(
    ("period", "delta", "timeframe"),
    [
        ("1D", timedelta(days=1), "5Min"),
        ("1W", timedelta(weeks=1), "1H"),
        ("1M", timedelta(days=30), "1D"),
        ("3M", timedelta(days=90), "1D"),
        ("1A", timedelta(days=365), "1D"),
        ("all", timedelta(days=1), "1D"),
    ],
)
def test_calculate_stock_period_returns_real_period_payloads(
    period: str,
    delta: timedelta,
    timeframe: str,
    stock_analytics_service: StockAnalyticsService,
) -> None:
    current_datetime = _utc_datetime(2024, 7, 5, 19, 0)
    earliest_price_datetime = stock_analytics_service.get_earliest_price_datetime(
        symbol="AAPL",
        current_datetime=current_datetime,
    )

    returned_period, payload = stock_analytics_service._calculate_stock_period(
        symbol="AAPL",
        current_datetime=current_datetime,
        earliest_price_datetime=earliest_price_datetime,
        period=period,
        delta=delta,
        timeframe=timeframe,
    )

    assert returned_period == period
    assert payload is not None
    _assert_period_payload_is_valid(payload, expected_timeframe=timeframe)
    assert payload["timestamp"][-1] <= current_datetime
    if period == "1D":
        assert payload["timestamp"][0] >= _utc_datetime(2024, 7, 5, 13, 30)
    elif period.upper() != "ALL":
        expected_start = current_datetime - delta
        assert expected_start - timedelta(days=1) <= payload["timestamp"][0]
        assert payload["timestamp"][0] <= expected_start + timedelta(days=1)


def test_calculate_stock_period_all_starts_at_earliest_available_price(
    stock_analytics_service: StockAnalyticsService,
) -> None:
    current_datetime = _utc_datetime(2024, 7, 5, 19, 0)
    earliest_price_datetime = stock_analytics_service.get_earliest_price_datetime(
        symbol="AAPL",
        current_datetime=current_datetime,
    )

    _, payload = stock_analytics_service._calculate_stock_period(
        symbol="AAPL",
        current_datetime=current_datetime,
        earliest_price_datetime=earliest_price_datetime,
        period="all",
        delta=timedelta(days=1),
        timeframe="1D",
    )

    assert payload is not None
    assert payload["timestamp"][0] >= earliest_price_datetime
    assert payload["timeframe"] == "1D"


def test_calculate_stock_period_returns_none_when_earliest_price_leaves_no_window(
    stock_analytics_service: StockAnalyticsService,
) -> None:
    current_datetime = _utc_datetime(2024, 7, 5, 19, 0)

    period, payload = stock_analytics_service._calculate_stock_period(
        symbol="AAPL",
        current_datetime=current_datetime,
        earliest_price_datetime=current_datetime,
        period="1W",
        delta=timedelta(weeks=1),
        timeframe="1H",
    )

    assert period == "1W"
    assert payload is None


@pytest.mark.parametrize(
    "current_datetime",
    [
        datetime(2024, 7, 8, 15, 0),
        _market_datetime(2024, 7, 8, 11, 0),
        datetime(2024, 7, 8, 8, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
        datetime(2024, 7, 8, 16, 0, tzinfo=timezone(timedelta(hours=1))),
    ],
)
def test_calculate_stock_period_rejects_non_utc_current_datetime(
    current_datetime: datetime,
    stock_analytics_service: StockAnalyticsService,
) -> None:
    with pytest.raises(StockAnalyticsInternalServerError) as error:
        stock_analytics_service._calculate_stock_period(
            symbol="AAPL",
            current_datetime=current_datetime,
            earliest_price_datetime=_utc_datetime(2020, 1, 1, 0),
            period="1W",
            delta=timedelta(weeks=1),
            timeframe="1H",
        )

    assert error.value.code == "STOCK_ANALYTICS_TIMEZONE_REQUIRED"


def test_calculate_stock_period_raises_for_natural_invalid_symbol_failure(
    stock_analytics_service: StockAnalyticsService,
) -> None:
    with pytest.raises(StockAnalyticsInternalServerError):
        stock_analytics_service._calculate_stock_period(
            symbol="NOTAREALBASKTSTOCK",
            current_datetime=_utc_datetime(2024, 7, 5, 19, 0),
            earliest_price_datetime=_utc_datetime(2020, 1, 1, 0),
            period="1W",
            delta=timedelta(weeks=1),
            timeframe="1H",
        )


def test_get_stock_analytics_by_periods_returns_default_periods_with_valid_metrics(
    stock_analytics_service: StockAnalyticsService,
) -> None:
    bars = stock_analytics_service.get_stock_analytics_by_periods(
        symbol="AAPL",
        current_datetime=_utc_datetime(2024, 7, 5, 19, 0),
    )

    assert list(bars) == ["1D", "1W", "1M", "3M", "1A", "all"]
    assert set(bars) == set(DEFAULT_PERIOD_TIMEFRAMES)
    for period, expected_timeframe in DEFAULT_PERIOD_TIMEFRAMES.items():
        _assert_period_payload_is_valid(
            bars[period],
            expected_timeframe=expected_timeframe,
        )


def test_get_stock_analytics_by_periods_filters_requested_periods(
    stock_analytics_service: StockAnalyticsService,
) -> None:
    bars = stock_analytics_service.get_stock_analytics_by_periods(
        symbol="AAPL",
        current_datetime=_utc_datetime(2024, 7, 5, 19, 0),
        periods=["1D", "1M"],
    )

    assert set(bars) == {"1D", "1M"}
    _assert_period_payload_is_valid(
        bars["1D"],
        expected_timeframe=DEFAULT_PERIOD_TIMEFRAMES["1D"],
    )
    _assert_period_payload_is_valid(
        bars["1M"],
        expected_timeframe=DEFAULT_PERIOD_TIMEFRAMES["1M"],
    )


def test_get_stock_analytics_by_periods_recent_ipo_one_year_period_uses_shortened_history(
    stock_analytics_service: StockAnalyticsService,
) -> None:
    symbol = "JMKE"
    current_datetime = _utc_datetime(2026, 8, 14, 20, 0)
    earliest_price_datetime = stock_analytics_service.get_earliest_price_datetime(
        symbol=symbol,
        current_datetime=current_datetime,
    )

    bars = stock_analytics_service.get_stock_analytics_by_periods(
        symbol=symbol,
        current_datetime=current_datetime,
    )

    assert earliest_price_datetime > current_datetime - timedelta(days=365)
    assert "1A" in bars
    _assert_period_payload_is_valid(
        bars["1A"],
        expected_timeframe=DEFAULT_PERIOD_TIMEFRAMES["1A"],
    )
    assert bars["1A"]["timestamp"][0] >= earliest_price_datetime
    assert bars["1A"]["timestamp"][0] > current_datetime - timedelta(days=365)
    assert bars["1A"]["timestamp"][-1] <= current_datetime


def test_get_stock_analytics_by_periods_uses_utc_now_when_current_datetime_is_missing(
    stock_analytics_service: StockAnalyticsService,
) -> None:
    bars = stock_analytics_service.get_stock_analytics_by_periods(symbol="AAPL")

    assert set(bars).issubset(set(DEFAULT_PERIOD_TIMEFRAMES))
    assert bars
    for period, payload in bars.items():
        _assert_period_payload_is_valid(
            payload,
            expected_timeframe=DEFAULT_PERIOD_TIMEFRAMES[period],
        )


@pytest.mark.parametrize(
    "current_datetime",
    [
        datetime(2024, 7, 5, 19, 0),
        _market_datetime(2024, 7, 5, 15, 0),
        datetime(2024, 7, 5, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
        datetime(2024, 7, 5, 20, 0, tzinfo=timezone(timedelta(hours=1))),
    ],
)
def test_get_stock_analytics_by_periods_rejects_non_utc_current_datetime(
    current_datetime: datetime,
    stock_analytics_service: StockAnalyticsService,
) -> None:
    with pytest.raises(StockAnalyticsInternalServerError) as error:
        stock_analytics_service.get_stock_analytics_by_periods(
            symbol="AAPL",
            current_datetime=current_datetime,
        )

    assert error.value.code == "STOCK_ANALYTICS_TIMEZONE_REQUIRED"


def test_get_stock_analytics_by_periods_raises_for_natural_invalid_symbol_failure(
    stock_analytics_service: StockAnalyticsService,
) -> None:
    with pytest.raises(StockAnalyticsInternalServerError):
        stock_analytics_service.get_stock_analytics_by_periods(
            symbol=f"NOTAREALBASKTSTOCK{datetime.now().microsecond}",
            current_datetime=_utc_datetime(2024, 7, 5, 19, 0),
        )
