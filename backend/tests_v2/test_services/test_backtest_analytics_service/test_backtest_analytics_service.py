"""
Coverage / scenarios:
- get_tradeable_fractionable_US_baskt_assets(): returns real Alpaca assets
  shaped as Stock domain objects with required tradable/fractionable metadata.
- run_backtest(): successful single-stock long, multi-stock long, mixed
  long/short, lowercase-symbol, same-day, weekend-inclusive, and deterministic
  repeated-call backtests return aligned timestamps/cumulative returns and all
  expected metric fields.
- run_backtest(): timestamps are sorted and stay within the requested date
  window, and cumulative returns/metrics are finite when present.
- run_backtest(): rejects empty positions, invalid date format, end_date before
  start_date, missing required fields including missing weight even when
  target_weight is present, invalid directions, and invalid numeric weight or
  leverage values.
- run_backtest(): raises data errors for symbols/date windows that cannot
  produce usable integrated market data.
- Not covered: leveraged happy paths, duplicate symbols, non-close price_col
  behavior, benchmark-missing internals, or mocked lower-level failures.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import pytest

from services.backtest_analytics_service import (
    BacktestService,
    BacktestServiceDataError,
    BacktestServiceValidationError,
)


pytestmark = pytest.mark.integration


METRIC_FIELDS = {
    "final_cumulative_return",
    "cagr",
    "leverage_adjusted_direction",
    "annualized_volatility",
    "alpha",
    "beta",
    "sharpe_ratio",
    "maximum_drawdown",
    "maximum_drawdown_duration",
}


def _position(
    *,
    symbol: str = "AAPL",
    weight: Any = 1.0,
    direction: Any = 1,
    leverage: Any = 1.0,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "weight": weight,
        "direction": direction,
        "leverage": leverage,
    }


def _run_backtest(
    backtest_service: BacktestService,
    *,
    start_date: str = "2024-07-01",
    end_date: str = "2024-07-31",
    positions_conf: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return backtest_service.run_backtest(
        start_date=start_date,
        end_date=end_date,
        positions_conf=positions_conf or [_position()],
    )


def _assert_numeric_or_none(value: Any) -> None:
    assert value is None or isinstance(value, (int, float))
    if isinstance(value, (int, float)):
        assert math.isfinite(float(value))


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _assert_successful_backtest_result(
    result: dict[str, Any],
    *,
    start_date: str,
    end_date: str,
) -> None:
    assert result["start_date"] == start_date
    assert result["end_date"] == end_date
    assert set(METRIC_FIELDS).issubset(result)

    timestamps = result["timestamps"]
    cumulative_returns = result["cumulative_returns"]
    assert timestamps
    assert cumulative_returns
    assert len(timestamps) == len(cumulative_returns)

    parsed_timestamps = [_parse_timestamp(timestamp) for timestamp in timestamps]
    assert parsed_timestamps == sorted(parsed_timestamps)
    assert parsed_timestamps[0].date() >= date.fromisoformat(start_date)
    assert parsed_timestamps[-1].date() <= date.fromisoformat(end_date)

    for cumulative_return in cumulative_returns:
        assert isinstance(cumulative_return, (int, float))
        assert math.isfinite(float(cumulative_return))

    for metric in METRIC_FIELDS:
        _assert_numeric_or_none(result[metric])


def _assert_results_close(
    first: dict[str, Any],
    second: dict[str, Any],
    *,
    tolerance: float = 1e-12,
) -> None:
    assert first["timestamps"] == second["timestamps"]
    assert len(first["cumulative_returns"]) == len(second["cumulative_returns"])
    for first_value, second_value in zip(
        first["cumulative_returns"],
        second["cumulative_returns"],
    ):
        assert float(first_value) == pytest.approx(float(second_value), abs=tolerance)
    for metric in METRIC_FIELDS:
        first_metric = first[metric]
        second_metric = second[metric]
        if first_metric is None or second_metric is None:
            assert first_metric is None and second_metric is None
            continue
        assert float(first_metric) == pytest.approx(
            float(second_metric),
            abs=tolerance,
        )


def test_backtest_service_get_tradeable_fractionable_us_baskt_assets(
    backtest_service: BacktestService,
) -> None:
    assets = backtest_service.get_tradeable_fractionable_US_baskt_assets()

    assert assets
    assert any(asset.symbol == "AAPL" for asset in assets)
    for asset in assets:
        assert asset.symbol
        assert asset.stock_id
        assert asset.tradable is True
        assert asset.fractionable is True
        assert str(asset.stock_class).upper() == "US_EQUITY"


@pytest.mark.parametrize(
    ("positions_conf", "start_date", "end_date"),
    [
        ([_position(symbol="AAPL", weight=1.0, direction=1)], "2024-07-01", "2024-07-31"),
        (
            [
                _position(symbol="AAPL", weight=0.4, direction=1),
                _position(symbol="MSFT", weight=0.35, direction=1),
                _position(symbol="GOOG", weight=0.25, direction=1),
            ],
            "2024-07-01",
            "2024-07-31",
        ),
        (
            [
                _position(symbol="AAPL", weight=0.6, direction=1),
                _position(symbol="MSFT", weight=0.4, direction=-1),
            ],
            "2024-07-01",
            "2024-07-31",
        ),
        ([_position(symbol="aapl", weight=1.0, direction=1)], "2024-07-01", "2024-07-31"),
        ([_position(symbol="AAPL", weight=1.0, direction=1)], "2024-07-05", "2024-07-05"),
        ([_position(symbol="AAPL", weight=1.0, direction=1)], "2024-07-05", "2024-07-08"),
    ],
)
def test_backtest_service_run_backtest_returns_integrated_analytics_payloads(
    backtest_service: BacktestService,
    positions_conf: list[dict[str, Any]],
    start_date: str,
    end_date: str,
) -> None:
    result = _run_backtest(
        backtest_service,
        start_date=start_date,
        end_date=end_date,
        positions_conf=positions_conf,
    )

    _assert_successful_backtest_result(
        result,
        start_date=start_date,
        end_date=end_date,
    )


def test_backtest_service_run_backtest_is_deterministic_for_closed_window(
    backtest_service: BacktestService,
) -> None:
    positions_conf = [
        _position(symbol="AAPL", weight=0.5, direction=1),
        _position(symbol="MSFT", weight=0.5, direction=1),
    ]

    first = _run_backtest(
        backtest_service,
        start_date="2024-07-01",
        end_date="2024-07-31",
        positions_conf=positions_conf,
    )
    second = _run_backtest(
        backtest_service,
        start_date="2024-07-01",
        end_date="2024-07-31",
        positions_conf=positions_conf,
    )

    _assert_results_close(first, second)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"positions_conf": []},
        {
            "start_date": "2024/07/01",
            "end_date": "2024-07-31",
            "positions_conf": [_position()],
        },
        {
            "start_date": "2024-07-31",
            "end_date": "2024-07-01",
            "positions_conf": [_position()],
        },
        {"positions_conf": [{"weight": 1.0, "direction": 1}]},
        {"positions_conf": [{"symbol": "AAPL", "direction": 1}]},
        {"positions_conf": [{"symbol": "AAPL", "target_weight": 1.0, "direction": 1}]},
        {"positions_conf": [{"symbol": "AAPL", "weight": 1.0}]},
        {"positions_conf": [_position(direction=0)]},
        {"positions_conf": [_position(direction=2)]},
        {"positions_conf": [_position(weight="not-a-number")]},
        {"positions_conf": [_position(leverage="not-a-number")]},
    ],
)
def test_backtest_service_run_backtest_rejects_invalid_inputs(
    backtest_service: BacktestService,
    kwargs: dict[str, Any],
) -> None:
    defaults = {
        "start_date": "2024-07-01",
        "end_date": "2024-07-31",
        "positions_conf": [_position()],
    }
    defaults.update(kwargs)

    with pytest.raises(BacktestServiceValidationError):
        backtest_service.run_backtest(**defaults)


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "start_date": "2024-07-01",
            "end_date": "2024-07-31",
            "positions_conf": [_position(symbol="NOTAREALBASKTTESTSYMBOL")],
        },
        {
            "start_date": "1900-01-01",
            "end_date": "1900-01-31",
            "positions_conf": [_position(symbol="AAPL")],
        },
    ],
)
def test_backtest_service_run_backtest_raises_data_error_for_unusable_market_data(
    backtest_service: BacktestService,
    kwargs: dict[str, Any],
) -> None:
    with pytest.raises(BacktestServiceDataError):
        backtest_service.run_backtest(**kwargs)
