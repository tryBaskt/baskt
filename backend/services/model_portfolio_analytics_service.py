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
    AssetAnalyticsServiceError,
)
from domain.model_portfolio_domain import ModelPortfolioSnapshot, ModelPortfolioAnalyticsPosition, ModelPortfolioAnalyticsSnapshot
from repository.model_portfolio_repository import ModelPortfolioRepository

# Third-party imports
import numpy as np
import pandas as pd


class ModelPortfolioAnalyticsServiceError(Exception):
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
            current_datetime: Timezone-aware timestamp used as "now."

        Returns:
            Tuple[datetime, datetime]: UTC start and end timestamps. During a
            trading session the end is current_datetime; otherwise the bounds
            cover the most recent completed trading session.

        Raises:
            ModelPortfolioAnalyticsServiceError: If current_datetime is naive
            or Alpaca returns no usable recent market session.
        """
        if (
            current_datetime.tzinfo is None
            or current_datetime.utcoffset() is None
        ):
            raise ModelPortfolioAnalyticsServiceError(
                message="current_datetime must be timezone-aware",
                code="MODEL_PORTFOLIO_ANALYTICS_TIMEZONE_REQUIRED",
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

        raise ModelPortfolioAnalyticsServiceError(
            message=(
                "No completed or active stock market session was found before "
                f"'{current_utc.isoformat()}'"
            ),
            code="MODEL_PORTFOLIO_ANALYTICS_MARKET_SESSION_NOT_FOUND",
        )


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
            ModelPortfolioAnalyticsServiceError: If Alpaca price lookup fails,
            a symbol price is missing, or the updated total value is zero.
        """
        try:
            symbols = [position.symbol for position in model_porfolio_snapshot.positions]
            symbol_prices_start = self.asset_analytics_service.get_prices_at_time(
                symbols=symbols,
                timestamp=start_datetime,
            )
            symbol_prices_end = self.asset_analytics_service.get_prices_at_time(
                symbols=symbols,
                timestamp=end_datetime,
            )

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
                raise ModelPortfolioAnalyticsServiceError(
                    message="Failed to calculate updated position weights because total ending value is zero",
                    code="MODEL_PORTFOLIO_ANALYTICS_UPDATED_WEIGHTS_ZERO_VALUE",
                )

            return {
                symbol: position_value / total_end_value
                for symbol, position_value in end_position_values.items()
            }
        except ModelPortfolioAnalyticsServiceError:
            raise
        except AssetAnalyticsServiceError as e:
            raise ModelPortfolioAnalyticsServiceError(
                message=f"Failed to fetch prices for updated model portfolio weights: {e}",
                code="MODEL_PORTFOLIO_ANALYTICS_UPDATED_WEIGHTS_PRICE_LOOKUP_FAILED",
            ) from e
        except Exception as e:
            raise ModelPortfolioAnalyticsServiceError(
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
            ModelPortfolioAnalyticsServiceError: If weights at the period
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
            AssetAnalyticsServiceError: If a required snapshot price cannot
                be fetched.
        """
        if not analytics_snapshots:
            return

        first_snapshot = analytics_snapshots[0]
        first_symbols = sorted(
            position.symbol for position in first_snapshot.positions
        )
        first_prices = self.asset_analytics_service.get_prices_at_time(
            symbols=first_symbols,
            timestamp=first_snapshot.timestamp,
        )
        for symbol, price in first_prices.items():
            segment_prices.loc[first_snapshot.timestamp, symbol] = price

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

            transition_prices = self.asset_analytics_service.get_prices_at_time(
                symbols=transition_symbols,
                timestamp=next_snapshot.timestamp,
            )
            for symbol, price in transition_prices.items():
                segment_prices.loc[next_snapshot.timestamp, symbol] = price

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
            ModelPortfolioAnalyticsServiceError: If required price data is
            missing or the period cannot be simulated.
            AssetAnalyticsServiceError: If market data cannot be fetched.
        """
        period_start_datetime = None
        period_end_datetime = current_datetime
        if period == "1D":
            (
                period_start_datetime,
                period_end_datetime,
            ) = self.get_one_day_session_bounds(current_datetime)

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
            return period, None

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
            raise ModelPortfolioAnalyticsServiceError(
                message=(
                    "No complete price data available for model "
                    f"portfolio '{portfolio_id}' during period '{period}'"
                ),
                code="MODEL_PORTFOLIO_ANALYTICS_PRICE_DATA_MISSING",
            )

        benchmark_symbol = "SPY"
        benchmark_prices_df = self.asset_analytics_service.get_prices_over_time(
            symbols=[benchmark_symbol],
            start_datetime=simulation_prices.index[0],
            end_datetime=period_end_datetime,
            timeframe=timeframe,
        )
        if benchmark_prices_df.empty or benchmark_symbol not in benchmark_prices_df:
            raise ModelPortfolioAnalyticsServiceError(
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
        )
        benchmark_prices = (
            benchmark_prices
            .reindex(benchmark_prices.index.union(simulation_prices.index))
            .sort_index()
            .ffill()
            .bfill()
            .reindex(simulation_prices.index)
        )
        benchmark_returns = benchmark_prices.pct_change()

        target_exposure = pd.DataFrame(
            np.nan,
            index=simulation_prices.index,
            columns=simulation_prices.columns,
            dtype=float,
        )
        for analytics_snapshot in analytics_snapshots:
            snapshot_timestamp = analytics_snapshot.timestamp
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
        except AssetAnalyticsServiceError as error:
            raise ModelPortfolioAnalyticsServiceError(
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




    def get_model_portfolio_bars(
        self,
        portfolio_id: str,
        current_datetime: Optional[datetime] = None
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
            ModelPortfolioAnalyticsServiceError: If portfolio history cannot be
            loaded, Alpaca price bars cannot be fetched, or any unexpected error
            occurs while calculating returns.
        """
        try:
            if not current_datetime:
                current_datetime = datetime.now(timezone.utc)

            period_timdelta_timeframe = [
                ("1D", timedelta(days=1),"5Min"),
                ("1W", timedelta(weeks=1), "1H"),
                ("1M", timedelta(days=30), "1D"),
                ("3M", timedelta(days=90), "1D"),
                ("1A", timedelta(days=365), "1D"),
                ("all", timedelta(days=1), "1D")
            ]

            model_portfolio_snapshots = self.model_portfolio_repository.get_position_history(portfolio_id=portfolio_id)
            if not model_portfolio_snapshots: 
                return {}
            model_portfolio_snapshots = sorted(
                model_portfolio_snapshots,
                key=lambda snapshot: snapshot.timestamp,
            )

            response: Dict[str, Dict[str, Any]] = {}

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
                max_workers=len(period_timdelta_timeframe),
                thread_name_prefix="model-portfolio-period",
            ) as executor:
                period_results = executor.map(
                    calculate_period,
                    period_timdelta_timeframe,
                )
                for period, period_response in period_results:
                    if period_response is not None:
                        response[period] = period_response

            return response

        except ModelPortfolioAnalyticsServiceError:
            raise
        except AssetAnalyticsServiceError as e:
            raise ModelPortfolioAnalyticsServiceError(
                message=f"Failed to get model portfolio price bars for portfolio '{portfolio_id}': {e}",
                code="MODEL_PORTFOLIO_ANALYTICS_GET_BARS_FAILED",
            ) from e
        except Exception as e:
            raise ModelPortfolioAnalyticsServiceError(
                message=f"Failed to calculate model portfolio bars for portfolio '{portfolio_id}': {e}",
                code="MODEL_PORTFOLIO_ANALYTICS_GET_BARS_FAILED",
            ) from e
