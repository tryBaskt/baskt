# backend/services/stock_analytics_service.py

# Python imports
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# Baskt imports
from services.asset_analytics_service import (
    AssetAnalyticsService,
    AssetAnalyticsInternalServerError,
)

# Third-party imports
import numpy as np
import pandas as pd


class StockAnalyticsInternalServerError(Exception):
	def __init__(self, message: str, code: str = "STOCK_ANALYTICS_SERVICE_ERROR") -> None:
		"""
		Initialize a stock analytics service exception.

		Args:
			message: Human-readable error details.
			code: Stable error code identifying the failed operation.

		Returns:
			None.
		"""
		super().__init__(message)
		self.code = code

class StockAnalyticsService:
    def __init__(
        self,
        *,
        asset_analytics_service: AssetAnalyticsService,
    ) -> None:
        self.asset_analytics_service = asset_analytics_service

    def get_one_day_session_bounds(
        self,
        current_datetime: datetime,
    ) -> Tuple[datetime, datetime]:
        """Resolve the market session represented by the 1D period.

        Args:
            current_datetime: Timezone-aware timestamp used as "now."

        Returns:
            Tuple[datetime, datetime]: UTC start and end timestamps. During a
            trading session the end is current_datetime; otherwise the bounds
            cover the most recent completed trading session.

        Raises:
            StockAnalyticsInternalServerError: If current_datetime is naive
            or Alpaca returns no usable recent market session.
        """
        if (
            current_datetime.tzinfo is None
            or current_datetime.utcoffset() is None
        ):
            raise StockAnalyticsInternalServerError(
                message="current_datetime must be timezone-aware",
                code="STOCK_ANALYTICS_TIMEZONE_REQUIRED",
            )

        current_utc = current_datetime.astimezone(timezone.utc)
        market_timezone = ZoneInfo("America/New_York")
        current_market_date = current_utc.astimezone(market_timezone).date()
        sessions = self.asset_analytics_service.get_market_calendar(
            start_date=current_market_date - timedelta(days=14),
            end_date=current_market_date,
        )

        normalized_sessions: List[Tuple[datetime, datetime]] = []
        for session in sessions:
            session_open = session.open
            session_close = session.close
            if session_open.tzinfo is None:
                session_open = session_open.replace(tzinfo=market_timezone)
            if session_close.tzinfo is None:
                session_close = session_close.replace(tzinfo=market_timezone)
            normalized_sessions.append(
                (
                    session_open.astimezone(timezone.utc),
                    session_close.astimezone(timezone.utc),
                )
            )

        normalized_sessions.sort(key=lambda bounds: bounds[0])
        for session_open, session_close in reversed(normalized_sessions):
            if session_open <= current_utc <= session_close:
                return session_open, current_utc
            if session_close < current_utc:
                return session_open, session_close

        raise StockAnalyticsInternalServerError(
            message=(
                "No completed or active stock market session was found before "
                f"'{current_utc.isoformat()}'"
            ),
            code="STOCK_ANALYTICS_MARKET_SESSION_NOT_FOUND",
        )



    def _calculate_stock_period(
        self,
        *,
        symbol: str,
        current_datetime: datetime,
        earliest_price_datetime: datetime,
        period: str,
        delta: timedelta,
        timeframe: str,
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """Calculate one stock analytics period.

        Args:
            symbol: Identifier of the stock.
            current_datetime: Timezone-aware analytics endpoint.
            earliest_price_datetime: Earliest available stock price timestamp.
            period: Period label included in the response.
            delta: Lookback duration used to select snapshots.
            timeframe: Alpaca and VectorBT bar timeframe.

        Returns:
            Tuple[str, Optional[Dict[str, Any]]]: Period label and its analytics
            payload, or None when the period has no usable snapshots.

        Raises:
            StockAnalyticsInternalServerError: If required price data is
            missing or the period cannot be simulated.
            AssetAnalyticsInternalServerError: If market data cannot be fetched.
        """
        if current_datetime.tzinfo is None or current_datetime.utcoffset() is None:
            raise StockAnalyticsInternalServerError(
                message="current_datetime must be timezone-aware",
                code="STOCK_ANALYTICS_TIMEZONE_REQUIRED",
            )

        current_datetime = current_datetime.astimezone(timezone.utc)
        earliest_price_datetime = earliest_price_datetime.astimezone(timezone.utc)
        period_start_datetime = current_datetime - delta
        period_end_datetime = current_datetime
        if period == "1D":
            (
                period_start_datetime,
                period_end_datetime,
            ) = self.get_one_day_session_bounds(current_datetime)
        elif period.upper() == "ALL":
            period_start_datetime = datetime(1970, 1, 1, tzinfo=timezone.utc)

        period_start_bounded_by_earliest_price = (
            period_start_datetime < earliest_price_datetime
        )
        if period_start_bounded_by_earliest_price:
            period_start_datetime = earliest_price_datetime
        if period_start_datetime >= period_end_datetime:
            return period, None

        try:
            benchmark_symbol = "SPY"
            market_data_symbols = list(dict.fromkeys([symbol, benchmark_symbol]))
            segment_prices_df = self.asset_analytics_service.get_prices_over_time(
                symbols=market_data_symbols,
                start_datetime=period_start_datetime,
                end_datetime=period_end_datetime,
                timeframe=timeframe,
                source=("yfinance" if period.upper() == "ALL" else "alpaca"),
            )
            if (
                period.upper() != "ALL"
                and not period_start_bounded_by_earliest_price
            ):
                should_seed_period_start = (
                    period_start_datetime not in segment_prices_df.index
                    or any(
                        symbol not in segment_prices_df.columns
                        or pd.isna(
                            segment_prices_df.loc[
                                period_start_datetime,
                                symbol,
                            ]
                        )
                        for symbol in market_data_symbols
                    )
                )
                if should_seed_period_start:
                    period_start_prices_df = (
                        self.asset_analytics_service.get_prices_at_time(
                            symbols=market_data_symbols,
                            timestamp=period_start_datetime,
                        )
                    )
                    for price_row in period_start_prices_df.itertuples(index=False):
                        segment_prices_df.loc[
                            price_row.timestamp,
                            price_row.symbol,
                        ] = price_row.price
        except AssetAnalyticsInternalServerError as error:
            raise StockAnalyticsInternalServerError(
                message=(
                    f"Failed to fetch prices for stock '{symbol}' during "
                    f"period '{period}': {error}"
                ),
                code="STOCK_ANALYTICS_PRICE_LOOKUP_FAILED",
            ) from error
        if segment_prices_df.empty:
            return period, None
        if symbol not in segment_prices_df.columns:
            raise StockAnalyticsInternalServerError(
                message=(
                    f"Price data for stock '{symbol}' is missing during "
                    f"period '{period}'"
                ),
                code="STOCK_ANALYTICS_PRICE_DATA_MISSING",
            )
        if benchmark_symbol not in segment_prices_df.columns:
            raise StockAnalyticsInternalServerError(
                message=(
                    f"Benchmark price data for '{benchmark_symbol}' is missing "
                    f"during period '{period}'"
                ),
                code="STOCK_ANALYTICS_BENCHMARK_DATA_MISSING",
            )

        aligned_prices = (
            segment_prices_df[market_data_symbols]
            .sort_index()
            .loc[lambda frame: ~frame.index.duplicated(keep="last")]
            .dropna()
        )
        simulation_prices = aligned_prices[[symbol]]
        if simulation_prices.empty:
            return period, None
        benchmark_returns = aligned_prices[benchmark_symbol].pct_change()

        target_exposure = pd.DataFrame(
            np.nan,
            index=simulation_prices.index,
            columns=simulation_prices.columns,
            dtype=float,
        )
        target_exposure.loc[simulation_prices.index[0], symbol] = 1.0

        vectorbt_frequency = {
            "5Min": "5min",
            "1H": "1h",
            "1D": "1d",
        }[timeframe]
        try:
            stock_analytics = self.asset_analytics_service.calculate_portfolio_analytics(
                prices=simulation_prices,
                target_exposure=target_exposure,
                frequency=vectorbt_frequency,
                initial_cash=10_000.0,
                fees=0.0,
                slippage=0.0,
                benchmark_returns=benchmark_returns,
            )
        except AssetAnalyticsInternalServerError as error:
            raise StockAnalyticsInternalServerError(
                message=(
                    "Failed to calculate stock performance for "
                    f"'{symbol}' during period '{period}': {error}"
                ),
                code="STOCK_ANALYTICS_CALCULATION_FAILED",
            ) from error

        return period, {
            "timeframe": timeframe,
            "timestamp": [timestamp for timestamp in stock_analytics.timestamps],
            "prices": [
                float(price)
                for price in simulation_prices[symbol].to_numpy()
            ],
            "final_cumulative_return": stock_analytics.final_cumulative_return,
            "cagr": stock_analytics.cagr,
            "annualized_volatility": stock_analytics.annualized_volatility,
            "leverage_adjusted_direction": stock_analytics.leverage_adjusted_direction,
            "alpha": stock_analytics.alpha,
            "beta": stock_analytics.beta,
            "sharpe_ratio": stock_analytics.sharpe_ratio,
            "maximum_drawdown": stock_analytics.maximum_drawdown,
            "maximum_drawdown_duration": stock_analytics.maximum_drawdown_duration,
        }




    def get_earliest_price_datetime(
        self,
        *,
        symbol: str,
        current_datetime: datetime,
    ) -> datetime:
        """Find the earliest available daily price timestamp for a stock."""
        if current_datetime.tzinfo is None or current_datetime.utcoffset() is None:
            raise StockAnalyticsInternalServerError(
                message="current_datetime must be timezone-aware",
                code="STOCK_ANALYTICS_TIMEZONE_REQUIRED",
            )

        try:
            prices_df = self.asset_analytics_service.get_prices_over_time(
                symbols=[symbol],
                start_datetime=datetime(1970, 1, 1, tzinfo=timezone.utc),
                end_datetime=current_datetime.astimezone(timezone.utc),
                timeframe="1D",
                source="yfinance",
            )
        except AssetAnalyticsInternalServerError as error:
            raise StockAnalyticsInternalServerError(
                message=(
                    f"Failed to fetch earliest price date for stock "
                    f"'{symbol}': {error}"
                ),
                code="STOCK_ANALYTICS_EARLIEST_PRICE_LOOKUP_FAILED",
            ) from error

        if prices_df.empty or symbol not in prices_df.columns:
            raise StockAnalyticsInternalServerError(
                message=f"No price history found for stock '{symbol}'",
                code="STOCK_ANALYTICS_PRICE_HISTORY_MISSING",
            )

        stock_prices = prices_df[symbol].dropna().sort_index()
        if stock_prices.empty:
            raise StockAnalyticsInternalServerError(
                message=f"No price history found for stock '{symbol}'",
                code="STOCK_ANALYTICS_PRICE_HISTORY_MISSING",
            )

        earliest_timestamp = stock_prices.index[0]
        if isinstance(earliest_timestamp, pd.Timestamp):
            earliest_datetime = earliest_timestamp.to_pydatetime()
        else:
            earliest_datetime = earliest_timestamp
        if earliest_datetime.tzinfo is None or earliest_datetime.utcoffset() is None:
            earliest_datetime = earliest_datetime.replace(tzinfo=timezone.utc)
        return earliest_datetime.astimezone(timezone.utc)


    def get_stock_bars(
        self,
        symbol: str,
        current_datetime: Optional[datetime] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get stock cumulative return series for standard periods.

        Args:
            symbol: Identifier of the stock to analyze.
            current_datetime: Optional UTC endpoint for the simulation.

        Returns:
            Dict[str, Dict[str, Any]]: Return series keyed by 1D, 1W, 1M,
            3M, 1A, and all. Each period contains its timeframe, timestamps,
            and cumulative returns.

        Raises:
            StockAnalyticsInternalServerError: Alpaca price bars cannot be fetched, or any unexpected error
            occurs while calculating returns.
        """
        try:
            if not current_datetime:
                current_datetime = datetime.now(timezone.utc)

            earliest_price_datetime = self.get_earliest_price_datetime(
                symbol=symbol,
                current_datetime=current_datetime,
            )

            period_timdelta_timeframe = [
                ("all", timedelta(days=1), "1D"),
                ("1D", timedelta(days=1),"5Min"),
                ("1W", timedelta(weeks=1), "1H"),
                ("1M", timedelta(days=30), "1D"),
                ("3M", timedelta(days=90), "1D"),
                ("1A", timedelta(days=365), "1D"),
            ]

            response: Dict[str, Dict[str, Any]] = {}

            def calculate_period(
                period_config: Tuple[str, timedelta, str],
            ) -> Tuple[str, Optional[Dict[str, Any]]]:
                period, delta, timeframe = period_config
                return self._calculate_stock_period(
                    symbol=symbol,
                    current_datetime=current_datetime,
                    earliest_price_datetime=earliest_price_datetime,
                    period=period,
                    delta=delta,
                    timeframe=timeframe,
                )

            with ThreadPoolExecutor(
                max_workers=len(period_timdelta_timeframe),
                thread_name_prefix="stock-period",
            ) as executor:
                period_results = executor.map(
                    calculate_period,
                    period_timdelta_timeframe,
                )
                for period, period_response in period_results:
                    if period_response is not None:
                        response[period] = period_response

            return response

        except StockAnalyticsInternalServerError:
            raise
        except AssetAnalyticsInternalServerError as e:
            raise StockAnalyticsInternalServerError(
                message=f"Failed to get stock price bars for stock '{symbol}': {e}",
                code="STOCK_ANALYTICS_GET_BARS_FAILED",
            ) from e
        except Exception as e:
            raise StockAnalyticsInternalServerError(
                message=f"Failed to calculate stock bars for stock '{symbol}': {e}",
                code="STOCK_ANALYTICS_GET_BARS_FAILED",
            ) from e
