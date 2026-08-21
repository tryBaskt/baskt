# backend/services/model_portfolio_analytics_service.py

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
from domain.model_portfolio_domain import ModelPortfolioSnapshot, ModelPortfolioAnalyticsPosition, ModelPortfolioAnalyticsSnapshot
from repository.model_portfolio_repository import ModelPortfolioRepository

# Third-party imports
import numpy as np
import pandas as pd


class ModelPortfolioAnalyticsInternalServerError(Exception):
	def __init__(self, message: str, code: str = "MODEL_PORTFOLIO_ANALYTICS_SERVICE_ERROR") -> None:
		"""
		Initialize a model portfolio analytics service exception.

		Args:
			message: Human-readable error details.
			code: Stable error code identifying the failed operation.

		Returns:
			None.
		"""
		super().__init__(message)
		self.code = code

class ModelPortfolioAnalyticsService:
    def __init__(
        self,
        *,
        model_portfolio_repository: ModelPortfolioRepository,
        asset_analytics_service: AssetAnalyticsService,
    ) -> None:
        self.model_portfolio_repository = model_portfolio_repository
        self.asset_analytics_service = asset_analytics_service

    def get_one_day_session_bounds(
        self,
        current_datetime: datetime,
    ) -> Tuple[datetime, datetime]:
        """Resolve the market session represented by the 1D period.

        Args:
            current_datetime: UTC timestamp used as "now."

        Returns:
            Tuple[datetime, datetime]: UTC start and end timestamps. During a
            trading session the end is current_datetime; otherwise the bounds
            cover the most recent completed trading session.

        Raises:
            ModelPortfolioAnalyticsInternalServerError: If current_datetime is
            not timezone-aware UTC or Alpaca returns no usable recent market
            session.
        """
        if (
            current_datetime.tzinfo is None
            or current_datetime.utcoffset() != timedelta(0)
        ):
            raise ModelPortfolioAnalyticsInternalServerError(
                message="current_datetime must be timezone-aware UTC",
                code="MODEL_PORTFOLIO_ANALYTICS_TIMEZONE_REQUIRED",
            )

        current_utc = current_datetime
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
            if session_open.tzinfo is None or session_open.utcoffset() is None:
                session_open = session_open.replace(tzinfo=market_timezone)
            if session_close.tzinfo is None or session_close.utcoffset() is None:
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

        raise ModelPortfolioAnalyticsInternalServerError(
            message=(
                "No completed or active stock market session was found before "
                f"'{current_utc.isoformat()}'"
            ),
            code="MODEL_PORTFOLIO_ANALYTICS_MARKET_SESSION_NOT_FOUND",
        )

    def _has_trading_time_between(
        self,
        *,
        start_datetime: datetime,
        end_datetime: datetime,
    ) -> bool:
        """Return True when a market session overlaps the given UTC window."""
        if end_datetime <= start_datetime:
            return False

        market_timezone = ZoneInfo("America/New_York")
        start_market_date = start_datetime.astimezone(market_timezone).date()
        end_market_date = end_datetime.astimezone(market_timezone).date()
        sessions = self.asset_analytics_service.get_market_calendar(
            start_date=start_market_date,
            end_date=end_market_date,
        )
        for session in sessions:
            session_open = session.open
            session_close = session.close
            if session_open.tzinfo is None or session_open.utcoffset() is None:
                session_open = session_open.replace(tzinfo=market_timezone)
            if session_close.tzinfo is None or session_close.utcoffset() is None:
                session_close = session_close.replace(tzinfo=market_timezone)

            session_open_utc = session_open.astimezone(timezone.utc)
            session_close_utc = session_close.astimezone(timezone.utc)
            if max(start_datetime, session_open_utc) < min(
                end_datetime,
                session_close_utc,
            ):
                return True

        return False

    def _has_expected_bar_since_creation(
        self,
        *,
        start_datetime: datetime,
        end_datetime: datetime,
        timeframe: str,
    ) -> bool:
        """Return True when the elapsed market time should have produced a bar."""
        if end_datetime <= start_datetime:
            return False

        normalized_timeframe = timeframe.lower()
        if normalized_timeframe in {"1d", "1day", "day"}:
            market_timezone = ZoneInfo("America/New_York")
            sessions = self.asset_analytics_service.get_market_calendar(
                start_date=start_datetime.astimezone(market_timezone).date(),
                end_date=end_datetime.astimezone(market_timezone).date(),
            )
            for session in sessions:
                session_close = session.close
                if session_close.tzinfo is None or session_close.utcoffset() is None:
                    session_close = session_close.replace(tzinfo=market_timezone)
                session_close_utc = session_close.astimezone(timezone.utc)
                if start_datetime < session_close_utc <= end_datetime:
                    return True
            return False

        required_market_seconds = {
            "5min": 5 * 60,
            "5m": 5 * 60,
            "1h": 60 * 60,
            "1hour": 60 * 60,
            "hour": 60 * 60,
        }.get(normalized_timeframe)
        if required_market_seconds is None:
            return self._has_trading_time_between(
                start_datetime=start_datetime,
                end_datetime=end_datetime,
            )

        market_timezone = ZoneInfo("America/New_York")
        sessions = self.asset_analytics_service.get_market_calendar(
            start_date=start_datetime.astimezone(market_timezone).date(),
            end_date=end_datetime.astimezone(market_timezone).date(),
        )
        elapsed_market_seconds = 0.0
        for session in sessions:
            session_open = session.open
            session_close = session.close
            if session_open.tzinfo is None or session_open.utcoffset() is None:
                session_open = session_open.replace(tzinfo=market_timezone)
            if session_close.tzinfo is None or session_close.utcoffset() is None:
                session_close = session_close.replace(tzinfo=market_timezone)

            session_open_utc = session_open.astimezone(timezone.utc)
            session_close_utc = session_close.astimezone(timezone.utc)
            overlap_start = max(start_datetime, session_open_utc)
            overlap_end = min(end_datetime, session_close_utc)
            if overlap_start < overlap_end:
                elapsed_market_seconds += (
                    overlap_end - overlap_start
                ).total_seconds()
                if elapsed_market_seconds >= required_market_seconds:
                    return True

        return False


    def get_positions_updated_weights(
        self,
        model_porfolio_snapshot: ModelPortfolioSnapshot,
        start_datetime: datetime,
        end_datetime: datetime,
    ) -> Dict[str, float]:
        """
        Calculate updated position weights between two timestamps.

        Args:
            model_porfolio_snapshot: Model portfolio snapshot whose positions
                should be reweighted.
            start_datetime: Timestamp to use for the starting position values.
            end_datetime: Timestamp to use for the ending position values.

        Returns:
            Dict[str, float]: Updated ending weight by symbol.

        Raises:
            ModelPortfolioAnalyticsInternalServerError: If Alpaca price lookup fails,
            a symbol price is missing, or the updated total value is zero.
        """
        try:
            symbols = [position.symbol for position in model_porfolio_snapshot.positions]
            symbol_prices_start_df = self.asset_analytics_service.get_prices_at_time(
                symbols=symbols,
                timestamp=start_datetime,
            )
            symbol_prices_end_df = self.asset_analytics_service.get_prices_at_time(
                symbols=symbols,
                timestamp=end_datetime,
            )
            symbol_prices_start = {
                str(symbol): float(price)
                for symbol, price in (
                    symbol_prices_start_df.set_index("symbol")["price"]
                    .to_dict()
                    .items()
                )
            }
            symbol_prices_end = {
                str(symbol): float(price)
                for symbol, price in (
                    symbol_prices_end_df.set_index("symbol")["price"]
                    .to_dict()
                    .items()
                )
            }

            start_position_values: Dict[str, float] = {}
            end_position_values: Dict[str, float] = {}

            for position in model_porfolio_snapshot.positions:
                start_price = symbol_prices_start[position.symbol]
                end_price = symbol_prices_end[position.symbol]

                start_position_values[position.symbol] = position.model_filled_quantity * (
                    position.model_filled_avg_price
                    + position.direction * (start_price - position.model_filled_avg_price)
                )
                end_position_values[position.symbol] = start_position_values[position.symbol] * (
                    1
                    + position.direction
                    * position.leverage
                    * ((end_price / start_price) - 1)
                )

            total_end_value = sum(end_position_values.values())
            if total_end_value == 0:
                raise ModelPortfolioAnalyticsInternalServerError(
                    message="Failed to calculate updated position weights because total ending value is zero",
                    code="MODEL_PORTFOLIO_ANALYTICS_UPDATED_WEIGHTS_ZERO_VALUE",
                )

            return {
                symbol: position_value / total_end_value
                for symbol, position_value in end_position_values.items()
            }
        except ModelPortfolioAnalyticsInternalServerError:
            raise
        except AssetAnalyticsInternalServerError as e:
            raise ModelPortfolioAnalyticsInternalServerError(
                message=f"Failed to fetch prices for updated model portfolio weights: {e}",
                code="MODEL_PORTFOLIO_ANALYTICS_UPDATED_WEIGHTS_PRICE_LOOKUP_FAILED",
            ) from e
        except Exception as e:
            raise ModelPortfolioAnalyticsInternalServerError(
                message=f"Failed to calculate updated model portfolio weights: {e}",
                code="MODEL_PORTFOLIO_ANALYTICS_UPDATED_WEIGHTS_FAILED",
            ) from e


    def get_analytics_snapshots(
        self,
        period: str,
        delta: timedelta,
        current_datetime: datetime,
        model_portfolio_snapshots: List[ModelPortfolioSnapshot],
        period_start_datetime: Optional[datetime] = None,
    ) -> List[ModelPortfolioAnalyticsSnapshot]:
        """Build the position snapshots active during an analytics period.

        Args:
            period: Requested analytics period.
            delta: Lookback duration for the period.
            current_datetime: Exclusive end of the analytics period.
            model_portfolio_snapshots: Portfolio position history in
                chronological order.
            period_start_datetime: Optional explicit period start. Used when
                the period must align to a market session.

        Returns:
            List[ModelPortfolioAnalyticsSnapshot]: Chronological snapshots,
            including a synthetic snapshot at the period start when needed.

        Raises:
            ModelPortfolioAnalyticsInternalServerError: If weights at the period
            boundary cannot be calculated.
        """
        current_period_start = (
            period_start_datetime
            if period_start_datetime is not None
            else current_datetime - delta
        )
        if period == "all":
            current_period_start = model_portfolio_snapshots[0].timestamp.replace(second=0, microsecond=0)

        if current_period_start >= current_datetime:
            return []

        analytics_snapshots: List[ModelPortfolioAnalyticsSnapshot] = []

        for i in range(len(model_portfolio_snapshots) - 1, -1, -1):
            snapshot = model_portfolio_snapshots[i]
            rounded_snapshot_timestamp = snapshot.timestamp.replace(second=0, microsecond=0)
            if rounded_snapshot_timestamp > current_datetime:
                continue
            if rounded_snapshot_timestamp > current_period_start:
                analytics_snapshot = ModelPortfolioAnalyticsSnapshot(
                    positions=[
                        ModelPortfolioAnalyticsPosition(
                            symbol=position.symbol,
                            direction=position.direction,
                            leverage=position.leverage,
                            current_weight=position.target_weight,
                        )
                        for position in snapshot.positions
                    ],
                    timestamp=rounded_snapshot_timestamp,
                )
                analytics_snapshots.append(analytics_snapshot)
            elif rounded_snapshot_timestamp <= current_period_start:
                if rounded_snapshot_timestamp == current_period_start:
                    position_updated_weights = {
                        position.symbol: position.target_weight
                        for position in snapshot.positions
                    }

                else:
                    position_updated_weights = self.get_positions_updated_weights(
                        model_porfolio_snapshot=snapshot,
                        start_datetime=rounded_snapshot_timestamp,
                        end_datetime=current_period_start,
                    )
                analytics_snapshot = ModelPortfolioAnalyticsSnapshot(
                    positions=[
                        ModelPortfolioAnalyticsPosition(
                            symbol=position.symbol,
                            direction=position.direction,
                            leverage=position.leverage,
                            current_weight=position_updated_weights[position.symbol],
                        )
                        for position in snapshot.positions
                    ],
                    timestamp=current_period_start,
                )
                analytics_snapshots.append(analytics_snapshot)
                break

        analytics_snapshots.reverse()
        return analytics_snapshots


    def get_stock_prices_at_snapshot_changes(
        self,
        segment_prices: pd.DataFrame,
        analytics_snapshots: List[ModelPortfolioAnalyticsSnapshot]
    ) -> None:
        """Get prices required at portfolio creation and update boundaries.

        Args:
            segment_prices: Price DataFrame to update in place. Rows are UTC
                timestamps and columns are stock symbols.
            analytics_snapshots: Chronological portfolio analytics snapshots.

        Returns:
            None. The provided segment_prices DataFrame is modified in place.

        Raises:
            AssetAnalyticsInternalServerError: If a required snapshot price cannot
                be fetched.
        """
        if not analytics_snapshots:
            return

        first_snapshot = analytics_snapshots[0]
        first_symbols = sorted(
            position.symbol for position in first_snapshot.positions
        )
        first_prices_df = self.asset_analytics_service.get_prices_at_time(
            symbols=first_symbols,
            timestamp=first_snapshot.timestamp,
        )
        for price_row in first_prices_df.itertuples(index=False):
            segment_prices.loc[price_row.timestamp, price_row.symbol] = price_row.price

        for index in range(len(analytics_snapshots) - 1):
            current_snapshot = analytics_snapshots[index]
            next_snapshot = analytics_snapshots[index + 1]
            current_symbols = {
                position.symbol for position in current_snapshot.positions
            }
            next_symbols = {
                position.symbol for position in next_snapshot.positions
            }
            transition_symbols = sorted(current_symbols | next_symbols)

            transition_prices_df = self.asset_analytics_service.get_prices_at_time(
                symbols=transition_symbols,
                timestamp=next_snapshot.timestamp,
            )
            for price_row in transition_prices_df.itertuples(index=False):
                segment_prices.loc[
                    price_row.timestamp,
                    price_row.symbol,
                ] = price_row.price

        segment_prices.index.name = "timestamp"
        segment_prices.sort_index(inplace=True)

    def _calculate_model_portfolio_period(
        self,
        *,
        portfolio_id: str,
        current_datetime: datetime,
        model_portfolio_snapshots: List[ModelPortfolioSnapshot],
        period: str,
        delta: timedelta,
        timeframe: str,
        portfolio_created_at: Optional[datetime] = None,
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """Calculate one model portfolio analytics period.

        Args:
            portfolio_id: Identifier of the model portfolio.
            current_datetime: Timezone-aware analytics endpoint.
            model_portfolio_snapshots: Chronological portfolio snapshots.
            period: Period label included in the response.
            delta: Lookback duration used to select snapshots.
            timeframe: Alpaca and VectorBT bar timeframe.

        Returns:
            Tuple[str, Optional[Dict[str, Any]]]: Period label and its analytics
            payload, or None when the period has no usable snapshots.

        Raises:
            ModelPortfolioAnalyticsInternalServerError: If required price data is
            missing or the period cannot be simulated.
            AssetAnalyticsInternalServerError: If market data cannot be fetched.
        """
        period_start_datetime = None
        period_end_datetime = current_datetime
        if period == "1D":
            (
                period_start_datetime,
                period_end_datetime,
            ) = self.get_one_day_session_bounds(current_datetime)
        portfolio_created_at = portfolio_created_at or min(
            snapshot.timestamp for snapshot in model_portfolio_snapshots
        )
        has_expected_bar_since_creation = self._has_expected_bar_since_creation(
            start_datetime=portfolio_created_at,
            end_datetime=current_datetime,
            timeframe=timeframe,
        )

        analytics_snapshots = self.get_analytics_snapshots(
            period=period,
            delta=delta,
            current_datetime=period_end_datetime,
            model_portfolio_snapshots=model_portfolio_snapshots,
            period_start_datetime=period_start_datetime,
        )
        full_segment_prices_df = pd.DataFrame()
        self.get_stock_prices_at_snapshot_changes(
            segment_prices=full_segment_prices_df,
            analytics_snapshots=analytics_snapshots,
        )
        if full_segment_prices_df.empty:
            if not has_expected_bar_since_creation:
                return period, None
            raise ModelPortfolioAnalyticsInternalServerError(
                message=(
                    "No model portfolio price data available after expected "
                    f"'{timeframe}' bar data should be available for "
                    f"portfolio '{portfolio_id}' during period '{period}'"
                ),
                code="MODEL_PORTFOLIO_ANALYTICS_PRICE_DATA_MISSING_AFTER_TRADING",
            )

        for index, analytics_snapshot in enumerate(analytics_snapshots):
            segment_start = analytics_snapshot.timestamp
            segment_end = (
                analytics_snapshots[index + 1].timestamp
                if index + 1 < len(analytics_snapshots)
                else period_end_datetime
            )
            symbols = [
                position.symbol for position in analytics_snapshot.positions
            ]
            segment_prices = self.asset_analytics_service.get_prices_over_time(
                symbols=symbols,
                start_datetime=segment_start,
                end_datetime=segment_end,
                timeframe=timeframe,
            )
            full_segment_prices_df = segment_prices.combine_first(
                full_segment_prices_df
            )
        
        simulation_prices = (
            full_segment_prices_df
            .sort_index()
            .loc[lambda frame: ~frame.index.duplicated(keep="last")]
            .ffill()
            .bfill()
        )
        if simulation_prices.empty or simulation_prices.isna().any().any():
            if not has_expected_bar_since_creation:
                return period, None
            raise ModelPortfolioAnalyticsInternalServerError(
                message=(
                    "No complete price data available for model "
                    f"portfolio '{portfolio_id}' during period '{period}'"
                ),
                code="MODEL_PORTFOLIO_ANALYTICS_PRICE_DATA_MISSING",
            )

        benchmark_symbol = "SPY"
        benchmark_start = simulation_prices.index[0]
        benchmark_prices_df = self.asset_analytics_service.get_prices_over_time(
            symbols=[benchmark_symbol],
            start_datetime=benchmark_start,
            end_datetime=period_end_datetime,
            timeframe=timeframe,
        )

        # Snapshot boundaries are synthetic rows in simulation_prices. Seed the
        # benchmark at those same timestamps, then align to exact shared
        # timestamps so standalone asset bars without benchmark bars do not
        # change volatility/alpha/beta relative to stock analytics.
        for analytics_snapshot in analytics_snapshots:
            snapshot_timestamp = analytics_snapshot.timestamp
            if (
                snapshot_timestamp in benchmark_prices_df.index
                and benchmark_symbol in benchmark_prices_df.columns
                and pd.notna(
                    benchmark_prices_df.loc[
                        snapshot_timestamp,
                        benchmark_symbol,
                    ]
                )
            ):
                continue
            benchmark_snapshot_prices_df = (
                self.asset_analytics_service.get_prices_at_time(
                    symbols=[benchmark_symbol],
                    timestamp=snapshot_timestamp,
                )
            )
            for price_row in benchmark_snapshot_prices_df.itertuples(index=False):
                if price_row.symbol != benchmark_symbol:
                    continue
                benchmark_timestamp = price_row.timestamp
                if (
                    benchmark_timestamp in benchmark_prices_df.index
                    and benchmark_symbol in benchmark_prices_df.columns
                    and pd.notna(
                        benchmark_prices_df.loc[
                            benchmark_timestamp,
                            benchmark_symbol,
                        ]
                    )
                ):
                    continue
                benchmark_prices_df.loc[
                    benchmark_timestamp,
                    benchmark_symbol,
                ] = price_row.price

        if benchmark_prices_df.empty or benchmark_symbol not in benchmark_prices_df:
            if not has_expected_bar_since_creation:
                return period, None
            raise ModelPortfolioAnalyticsInternalServerError(
                message=(
                    f"Benchmark price data for '{benchmark_symbol}' is missing "
                    f"during period '{period}'"
                ),
                code="MODEL_PORTFOLIO_ANALYTICS_BENCHMARK_DATA_MISSING",
            )
        benchmark_prices = (
            benchmark_prices_df[benchmark_symbol]
            .sort_index()
            .loc[lambda series: ~series.index.duplicated(keep="last")]
            .dropna()
        )
        common_price_index = simulation_prices.index.intersection(
            benchmark_prices.index
        )
        simulation_prices = simulation_prices.loc[common_price_index]
        benchmark_prices = benchmark_prices.loc[common_price_index]
        if (
            simulation_prices.empty
            or benchmark_prices.empty
            or len(common_price_index) < 2
        ):
            if not has_expected_bar_since_creation:
                return period, None
            raise ModelPortfolioAnalyticsInternalServerError(
                message=(
                    "No benchmark-aligned price data available after expected "
                    f"'{timeframe}' bar data should be available for model "
                    f"portfolio '{portfolio_id}' during period '{period}'"
                ),
                code="MODEL_PORTFOLIO_ANALYTICS_BENCHMARK_ALIGNED_PRICE_DATA_MISSING",
            )
        benchmark_returns = benchmark_prices.pct_change()

        target_exposure = pd.DataFrame(
            np.nan,
            index=simulation_prices.index,
            columns=simulation_prices.columns,
            dtype=float,
        )
        for analytics_snapshot in analytics_snapshots:
            snapshot_timestamps = simulation_prices.index[
                simulation_prices.index <= analytics_snapshot.timestamp
            ]
            snapshot_timestamp = (
                snapshot_timestamps[-1]
                if not snapshot_timestamps.empty
                else simulation_prices.index[0]
            )
            target_exposure.loc[snapshot_timestamp, :] = 0.0
            for position in analytics_snapshot.positions:
                position_exposure = (
                    position.current_weight
                    * position.direction
                    * position.leverage
                )
                target_exposure.loc[
                    snapshot_timestamp,
                    position.symbol,
                ] = position_exposure

        vectorbt_frequency = {
            "5Min": "5min",
            "1H": "1h",
            "1D": "1d",
        }[timeframe]

        try:
            model_portfolio_analytics = self.asset_analytics_service.calculate_portfolio_analytics(
                prices=simulation_prices,
                target_exposure=target_exposure,
                frequency=vectorbt_frequency,
                initial_cash=10_000.0,
                fees=0.0,
                slippage=0.0,
                benchmark_returns=benchmark_returns,
            )
        except AssetAnalyticsInternalServerError as error:
            raise ModelPortfolioAnalyticsInternalServerError(
                message=(
                    "Failed to calculate model portfolio performance for "
                    f"'{portfolio_id}' during period '{period}': {error}"
                ),
                code="MODEL_PORTFOLIO_ANALYTICS_CALCULATION_FAILED",
            ) from error

        return period, {
            "timeframe": timeframe,
            "timestamp": [timestamp for timestamp in model_portfolio_analytics.timestamps],
            "cumulative_returns": [
                cumulative_return * 100.0
                for cumulative_return in model_portfolio_analytics.cumulative_returns
            ],
            "final_cumulative_return": model_portfolio_analytics.final_cumulative_return,
            "cagr": model_portfolio_analytics.cagr,
            "annualized_volatility": model_portfolio_analytics.annualized_volatility,
            "leverage_adjusted_direction": model_portfolio_analytics.leverage_adjusted_direction,
            "alpha": model_portfolio_analytics.alpha,
            "beta": model_portfolio_analytics.beta,
            "sharpe_ratio": model_portfolio_analytics.sharpe_ratio,
            "maximum_drawdown": model_portfolio_analytics.maximum_drawdown,
            "maximum_drawdown_duration": model_portfolio_analytics.maximum_drawdown_duration,
        }

    def calculate_trading_minutes(
        self,
        model_portfolio_created_at: datetime,
        current_datetime: datetime,
    ) -> int:
        if (
            model_portfolio_created_at.tzinfo is None
            or model_portfolio_created_at.utcoffset() != timedelta(0)
            or current_datetime.tzinfo is None
            or current_datetime.utcoffset() != timedelta(0)
        ):
            raise ModelPortfolioAnalyticsInternalServerError(
                message="model_portfolio_created_at and current_datetime must be timezone-aware UTC",
                code="MODEL_PORTFOLIO_ANALYTICS_TIMEZONE_REQUIRED",
            )

        if current_datetime <= model_portfolio_created_at:
            return 0

        try:
            market_timezone = ZoneInfo("America/New_York")
            sessions = self.asset_analytics_service.get_market_calendar(
                start_date=model_portfolio_created_at.astimezone(market_timezone).date(),
                end_date=current_datetime.astimezone(market_timezone).date(),
            )

            trading_seconds = 0.0
            for session in sessions:
                session_open = session.open
                session_close = session.close
                if session_open.tzinfo is None or session_open.utcoffset() is None:
                    session_open = session_open.replace(tzinfo=market_timezone)
                if session_close.tzinfo is None or session_close.utcoffset() is None:
                    session_close = session_close.replace(tzinfo=market_timezone)

                session_open_utc = session_open.astimezone(timezone.utc)
                session_close_utc = session_close.astimezone(timezone.utc)
                trading_start = max(model_portfolio_created_at, session_open_utc)
                trading_end = min(current_datetime, session_close_utc)
                if trading_start < trading_end:
                    trading_seconds += (trading_end - trading_start).total_seconds()

            return int(trading_seconds // 60)
        except AssetAnalyticsInternalServerError as error:
            raise ModelPortfolioAnalyticsInternalServerError(
                message=f"Failed to calculate model portfolio trading minutes: {error}",
                code="MODEL_PORTFOLIO_ANALYTICS_TRADING_MINUTES_FAILED",
            ) from error

    def get_model_portfolio_bars(
        self,
        portfolio_id: str,
        current_datetime: Optional[datetime] = None,
        period_timedelta_timeframe: List[Tuple[str,timedelta, str]] = [
                ("1D", timedelta(days=1),"5Min"),
                ("1W", timedelta(weeks=1), "1H"),
                ("1M", timedelta(days=30), "1D"),
                ("3M", timedelta(days=90), "1D"),
                ("1A", timedelta(days=365), "1D"),
                ("all", timedelta(days=1), "1D")
            ]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get model portfolio cumulative return series for standard periods.

        Args:
            portfolio_id: Identifier of the model portfolio to analyze.
            current_datetime: Optional UTC endpoint for the simulation.

        Returns:
            Dict[str, Dict[str, Any]]: Return series keyed by 1D, 1W, 1M,
            3M, 1A, and all. Each period contains its timeframe, timestamps,
            and cumulative returns.

        Raises:
            ModelPortfolioAnalyticsInternalServerError: If portfolio history cannot be
            loaded, Alpaca price bars cannot be fetched, or any unexpected error
            occurs while calculating returns.
        """
        try:
            if not current_datetime:
                current_datetime = datetime.now(timezone.utc)

            model_portfolio = self.model_portfolio_repository.get_model_portfolio(portfolio_id=portfolio_id)
            model_portfolio_snapshots = model_portfolio.position_history
            trading_minutes = self.calculate_trading_minutes(model_portfolio_created_at=model_portfolio.created_at, current_datetime=current_datetime)

            if trading_minutes < 5 or not model_portfolio_snapshots:
                return {}

            model_portfolio_snapshots = sorted(
                model_portfolio_snapshots,
                key=lambda snapshot: snapshot.timestamp,
            )

            response: Dict[str, Dict[str, Any]] = {}

            one_trading_day_minutes = int(60 * 6.5)
            one_trading_week_minutes = one_trading_day_minutes * 7

            if 5 <= trading_minutes <= one_trading_day_minutes:
                _, period_response = self._calculate_model_portfolio_period(
                    portfolio_id=portfolio_id,
                    current_datetime=current_datetime,
                    model_portfolio_snapshots=model_portfolio_snapshots,
                    period="1D",
                    delta=timedelta(days=1),
                    timeframe="5Min"
                )
                response = {
                    "1D": period_response,
                    "1W": period_response,
                    "1M": period_response,
                    "3M": period_response,
                    "1A": period_response,
                    "all": period_response
                }
            elif one_trading_day_minutes < trading_minutes < one_trading_week_minutes:
                print("sdjfoisdjof")
                _, daily_response = self._calculate_model_portfolio_period(
                    portfolio_id=portfolio_id,
                    current_datetime=current_datetime,
                    model_portfolio_snapshots=model_portfolio_snapshots,
                    period="1D",
                    delta=timedelta(days=1),
                    timeframe="5Min"
                )
                _, weekly_response = self._calculate_model_portfolio_period(
                    portfolio_id=portfolio_id,
                    current_datetime=current_datetime,
                    model_portfolio_snapshots=model_portfolio_snapshots,
                    period="1W",
                    delta=timedelta(weeks=1),
                    timeframe="1H"
                )

                response = {
                    "1D": daily_response,
                    "1W": weekly_response,
                    "1M": weekly_response,
                    "3M": weekly_response,
                    "1A": weekly_response,
                    "all": weekly_response
                }

            else:
                def calculate_period(
                    period_config: Tuple[str, timedelta, str],
                ) -> Tuple[str, Optional[Dict[str, Any]]]:
                    period, delta, timeframe = period_config
                    return self._calculate_model_portfolio_period(
                        portfolio_id=portfolio_id,
                        current_datetime=current_datetime,
                        model_portfolio_snapshots=model_portfolio_snapshots,
                        period=period,
                        delta=delta,
                        timeframe=timeframe,
                    )

                with ThreadPoolExecutor(
                    max_workers=len(period_timedelta_timeframe),
                    thread_name_prefix="model-portfolio-period",
                ) as executor:
                    period_results = executor.map(
                        calculate_period,
                        period_timedelta_timeframe,
                    )
                    for period, period_response in period_results:
                        if period_response is not None:
                            response[period] = period_response

            return response

        except ModelPortfolioAnalyticsInternalServerError:
            raise
        except AssetAnalyticsInternalServerError as e:
            raise ModelPortfolioAnalyticsInternalServerError(
                message=f"Failed to get model portfolio price bars for portfolio '{portfolio_id}': {e}",
                code="MODEL_PORTFOLIO_ANALYTICS_GET_BARS_FAILED",
            ) from e
        except Exception as e:
            raise ModelPortfolioAnalyticsInternalServerError(
                message=f"Failed to calculate model portfolio bars for portfolio '{portfolio_id}': {e}",
                code="MODEL_PORTFOLIO_ANALYTICS_GET_BARS_FAILED",
            ) from e
        
