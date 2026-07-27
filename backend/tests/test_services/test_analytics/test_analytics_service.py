from datetime import datetime, timedelta, timezone
from math import isfinite

import pytest

from .conftest import TestEngine


METRICS_TO_COMPARE = (
    "final_cumulative_return",
    "cagr",
    "annualized_volatility",
    "leverage_adjusted_direction",
    "alpha",
    "beta",
    # "sharpe_ratio",
    "maximum_drawdown",
    "maximum_drawdown_duration",
)

PERIODS_TO_COMPARE = ("1D", "1W", "1M", "3M", "1A")
ABSOLUTE_TOLERANCE = 0.001
BACKTEST_ABSOLUTE_TOLERANCE = 0.1
DEFAULT_RELATIVE_TOLERANCE = 1e-4
BACKTEST_PERIOD_WINDOWS = {
    "1M": timedelta(days=30),
    "3M": timedelta(days=90),
}


def _assert_metrics_match(
    *,
    expected_metrics: dict,
    actual_metrics: dict,
    context: str,
    absolute_tolerance: float = ABSOLUTE_TOLERANCE,
) -> None:
    for metric in METRICS_TO_COMPARE:
        expected_value = expected_metrics[metric]
        actual_value = actual_metrics[metric]
        if expected_value is None or actual_value is None:
            assert expected_value is actual_value
            continue

        assert isfinite(expected_value)
        assert isfinite(actual_value)
        assert actual_value == pytest.approx(
            expected_value,
            rel=DEFAULT_RELATIVE_TOLERANCE,
            abs=absolute_tolerance,
        ), f"{context} {metric} differs"


@pytest.mark.integration
def test_single_apple_model_portfolio_matches_apple_stock_analytics(
    test_engine: TestEngine,
) -> None:
    symbol = "AAPL"
    current_datetime = datetime(2024, 1, 2, 14, 0, tzinfo=timezone.utc)
    portfolio_id = None

    try:
        earliest_aapl_timestamp = test_engine.get_earliest_analytics_compatible_stock_timestamp(
            symbol=symbol,
        )
        portfolio_id = test_engine.create_single_stock_model_portfolio(
            symbol=symbol,
            creation_time=earliest_aapl_timestamp,
        )

        stock_metrics_by_period = test_engine.get_stock_metrics(
            symbol=symbol,
            current_datetime=current_datetime,
        )
        portfolio_metrics_by_period = test_engine.get_model_portfolio_metrics(
            portfolio_id=portfolio_id,
            current_datetime=current_datetime,
        )

        for period in PERIODS_TO_COMPARE:
            assert period in stock_metrics_by_period
            assert period in portfolio_metrics_by_period
            stock_metrics = stock_metrics_by_period[period]
            portfolio_metrics = portfolio_metrics_by_period[period]

            assert stock_metrics["timeframe"] == portfolio_metrics["timeframe"]
            assert stock_metrics["timestamp"]
            assert portfolio_metrics["timestamp"]

            _assert_metrics_match(
                expected_metrics=stock_metrics,
                actual_metrics=portfolio_metrics,
                context=period,
            )
    finally:
        if portfolio_id is not None:
            test_engine.delete_model_portfolio(portfolio_id=portfolio_id)


@pytest.mark.integration
def test_single_apple_backtest_stock_and_model_portfolio_analytics_match(
    test_engine: TestEngine,
) -> None:
    symbol = "AAPL"
    current_datetime = datetime(2024, 1, 2, 14, 0, tzinfo=timezone.utc)
    portfolio_id = None

    try:
        earliest_aapl_timestamp = test_engine.get_earliest_analytics_compatible_stock_timestamp(
            symbol=symbol,
        )
        portfolio_id = test_engine.create_single_stock_model_portfolio(
            symbol=symbol,
            creation_time=earliest_aapl_timestamp,
        )

        stock_metrics_by_period = test_engine.get_stock_metrics(
            symbol=symbol,
            current_datetime=current_datetime,
        )
        portfolio_metrics_by_period = test_engine.get_model_portfolio_metrics(
            portfolio_id=portfolio_id,
            current_datetime=current_datetime,
        )

        for period, delta in BACKTEST_PERIOD_WINDOWS.items():
            period_start_datetime = current_datetime - delta
            backtest_metrics = test_engine.get_backtest_metrics(
                symbol=symbol,
                start_date=period_start_datetime.date().isoformat(),
                end_date=current_datetime.date().isoformat(),
            )

            assert period in stock_metrics_by_period
            assert period in portfolio_metrics_by_period
            assert backtest_metrics["timestamps"]
            assert stock_metrics_by_period[period]["timestamp"]
            assert portfolio_metrics_by_period[period]["timestamp"]

            _assert_metrics_match(
                expected_metrics=backtest_metrics,
                actual_metrics=stock_metrics_by_period[period],
                context=f"{period} stock analytics",
                absolute_tolerance=BACKTEST_ABSOLUTE_TOLERANCE,
            )
            _assert_metrics_match(
                expected_metrics=backtest_metrics,
                actual_metrics=portfolio_metrics_by_period[period],
                context=f"{period} model portfolio analytics",
                absolute_tolerance=BACKTEST_ABSOLUTE_TOLERANCE,
            )
    finally:
        if portfolio_id is not None:
            test_engine.delete_model_portfolio(portfolio_id=portfolio_id)
