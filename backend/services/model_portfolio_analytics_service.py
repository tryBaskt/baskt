# backend/services/model_portfolio_analytics_service.py

# Python imports
from __future__ import annotations
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from math import sqrt

# Baskt imports
from clients.alpaca_broker_client import AlpacaBrokerClient, AlpacaBrokerClientError
from domain.model_portfolio import ModelPortfolioSnapshot
from repository.model_portfolio_repository import ModelPortfolioRepository
from domain.model_portfolio_analytics import ModelPortfolioAnalyticsPosition, ModelPortfolioAnalyticsSnapshot

# import pandas
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
        alpaca_broker_client: AlpacaBrokerClient,
        model_portfolio_repository: ModelPortfolioRepository
    ) -> None:
        self.alpaca_broker_client = alpaca_broker_client
        self.model_portfolio_repository = model_portfolio_repository


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
            symbol_prices_start = self.alpaca_broker_client.get_stocks_prices_at_time(
                symbols=symbols,
                timestamp=start_datetime,
            )
            symbol_prices_end = self.alpaca_broker_client.get_stocks_prices_at_time(
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
        except AlpacaBrokerClientError as e:
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
    ) -> List[ModelPortfolioAnalyticsSnapshot]:
        """Build the position snapshots active during an analytics period.

        Args:
            period: Requested analytics period.
            delta: Lookback duration for the period.
            current_datetime: Exclusive end of the analytics period.
            model_portfolio_snapshots: Portfolio position history in
                chronological order.

        Returns:
            List[ModelPortfolioAnalyticsSnapshot]: Chronological snapshots,
            including a synthetic snapshot at the period start when needed.

        Raises:
            ModelPortfolioAnalyticsServiceError: If weights at the period
            boundary cannot be calculated.
        """
        current_period_start = current_datetime - delta
        if period == "1D":
            current_period_start = datetime.combine(
                current_datetime.date(),
                datetime.min.time().replace(hour=14, minute=30, second=0, microsecond=0),
                tzinfo=timezone.utc,
            )
        if period == "all":
            current_period_start = model_portfolio_snapshots[0].timestamp.replace(second=0, microsecond=0)

        if current_period_start >= current_datetime:
            return []

        analytics_snapshots: List[ModelPortfolioAnalyticsSnapshot] = []

        for i in range(len(model_portfolio_snapshots) - 1, -1, -1):
            snapshot = model_portfolio_snapshots[i]
            rounded_snapshot_timestamp = snapshot.timestamp.replace(second=0, microsecond=0)
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


    def get_stocks_dataframe(
        self,
        analytics_snapshots: List[ModelPortfolioAnalyticsSnapshot],
        current_datetime: datetime,
        timeframe: str,
    ) -> pd.DataFrame:
        """Fetch and combine stock prices for each position snapshot.

        Args:
            analytics_snapshots: Chronological analytics snapshots.
            current_datetime: Exclusive end of the final snapshot.
            timeframe: Alpaca bar timeframe.

        Returns:
            pd.DataFrame: UTC-indexed close prices with symbols as columns.

        Raises:
            AlpacaBrokerClientError: If an Alpaca price-bars request fails.
        """
        if not analytics_snapshots:
            return pd.DataFrame()

        length_analytics_snapshots = len(analytics_snapshots)
        all_analytics_snapshots_df = pd.DataFrame()
        for i in range(length_analytics_snapshots):
            analytics_snapshot = analytics_snapshots[i]
            start_timestamp = analytics_snapshot.timestamp
            end_timestamp = current_datetime

            if i < length_analytics_snapshots-1:
                end_timestamp = (analytics_snapshots[i + 1].timestamp).replace(second=0, microsecond=0)

            analytics_snapshot_df = self.alpaca_broker_client.get_stock_prices_over_time(
                symbols=[position.symbol for position in analytics_snapshot.positions],
                start_datetime=start_timestamp,
                end_datetime=end_timestamp,
                timeframe=timeframe
            )

            all_analytics_snapshots_df = pd.concat(
                [all_analytics_snapshots_df, analytics_snapshot_df],
                axis=0,
            ).sort_index()

        return all_analytics_snapshots_df


    def get_cumulative_returns_dataframe(
        self,
        stocks_df: pd.DataFrame,
        analytics_snapshots: List[ModelPortfolioAnalyticsSnapshot],
        current_datetime: datetime,
    ) -> pd.DataFrame:
        """Calculate a cumulative return series across portfolio snapshots.

        Args:
            stocks_df: UTC-indexed close prices with symbols as columns.
            analytics_snapshots: Chronological position snapshots.
            current_datetime: Inclusive upper bound for available final bars.

        Returns:
            pd.DataFrame: UTC-indexed cumulative returns in percent.
        """
        if stocks_df.empty or not analytics_snapshots:
            return pd.DataFrame(columns=["cumulative_returns"])

        length_analytics_snapshots = len(analytics_snapshots)
        cumulative_return_frames: List[pd.DataFrame] = []
        segment_base_value = 1.0
        for i in range(length_analytics_snapshots):
            analytics_snapshot = analytics_snapshots[i]
            active_symbols = [position.symbol for position in analytics_snapshot.positions]
            segment_start_timestamp = analytics_snapshot.timestamp
            if i < length_analytics_snapshots - 1:
                next_snapshot_timestamp = analytics_snapshots[i + 1].timestamp
                segment_mask = (
                    (stocks_df.index >= segment_start_timestamp)
                    & (stocks_df.index < next_snapshot_timestamp)
                )
            else:
                segment_mask = (
                    (stocks_df.index >= segment_start_timestamp)
                    & (stocks_df.index <= current_datetime)
                )

            segment_prices_df = stocks_df.loc[segment_mask, active_symbols].ffill()
            segment_prices_df = segment_prices_df.dropna(subset=active_symbols)
            if segment_prices_df.empty:
                continue

            start_prices = segment_prices_df.iloc[0]
            weighted_returns = pd.Series(0.0, index=segment_prices_df.index)
            for position in analytics_snapshot.positions:
                weighted_returns = weighted_returns + (
                    position.current_weight
                    * position.direction
                    * position.leverage
                    * (
                        (segment_prices_df[position.symbol] / start_prices[position.symbol])
                        - 1
                    )
                )

            segment_cumulative_returns = (segment_base_value * (1 + weighted_returns)) - 1
            cumulative_return_frame = pd.DataFrame(
                {
                    "cumulative_returns": segment_cumulative_returns * 100,
                }
            )
            cumulative_return_frames.append(cumulative_return_frame)
            segment_base_value = 1 + float(segment_cumulative_returns.iloc[-1])

        cumulative_returns_df = (
            pd.concat(cumulative_return_frames, axis=0).sort_index()
            if cumulative_return_frames
            else pd.DataFrame(columns=["cumulative_returns"])
        )

        return cumulative_returns_df


    def calculate_period_metrics(
        self,
        cumulative_returns_df: pd.DataFrame,
        analytics_snapshots: List[ModelPortfolioAnalyticsSnapshot],
        timeframe: str,
    ) -> Dict[str, Optional[float]]:
        """Calculate summary metrics for one model portfolio period.

        Args:
            cumulative_returns_df: UTC-indexed cumulative returns expressed in
                percentage points.
            analytics_snapshots: Chronological position snapshots used for the
                period calculation.
            timeframe: Alpaca bar timeframe used by the return series.

        Returns:
            Dict[str, Optional[float]]: CAGR and annualized volatility as
            decimal returns, plus the latest leverage-adjusted direction tilt.
        """
        leverage_adjusted_direction = None
        if analytics_snapshots:
            leverage_adjusted_direction = float(
                sum(
                    position.current_weight * position.direction * position.leverage
                    for position in analytics_snapshots[-1].positions
                )
            )

        if len(cumulative_returns_df.index) < 2:
            return {
                "cagr": None,
                "annualized_volatility": None,
                "leverage_adjusted_direction": leverage_adjusted_direction,
            }

        cumulative_returns = cumulative_returns_df["cumulative_returns"] / 100
        portfolio_values = 1 + cumulative_returns
        initial_value = float(portfolio_values.iloc[0])
        final_value = float(portfolio_values.iloc[-1])
        elapsed_seconds = (
            cumulative_returns_df.index[-1] - cumulative_returns_df.index[0]
        ).total_seconds()

        cagr = None
        if initial_value > 0 and final_value > 0 and elapsed_seconds > 0:
            elapsed_years = elapsed_seconds / (365.25 * 24 * 60 * 60)
            cagr = float((final_value / initial_value) ** (1 / elapsed_years) - 1)

        periods_per_year = {
            "5min": 252 * 78,
            "1h": 252 * 6.5,
            "1d": 252,
        }.get(timeframe.lower())
        periodic_returns = portfolio_values.pct_change().dropna()
        annualized_volatility = None
        if periods_per_year and len(periodic_returns) >= 2:
            volatility = periodic_returns.std(ddof=1) * sqrt(periods_per_year)
            if not pd.isna(volatility):
                annualized_volatility = float(volatility)

        return {
            "cagr": cagr,
            "annualized_volatility": annualized_volatility,
            "leverage_adjusted_direction": leverage_adjusted_direction,
        }

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
            AlpacaBrokerClientError: If a required snapshot price cannot be
            fetched from Alpaca.
        """
        if not analytics_snapshots:
            return

        first_snapshot = analytics_snapshots[0]
        first_symbols = sorted(
            position.symbol for position in first_snapshot.positions
        )
        first_prices = self.alpaca_broker_client.get_stocks_prices_at_time(
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

            transition_prices = self.alpaca_broker_client.get_stocks_prices_at_time(
                symbols=transition_symbols,
                timestamp=next_snapshot.timestamp,
            )
            for symbol, price in transition_prices.items():
                segment_prices.loc[next_snapshot.timestamp, symbol] = price

        segment_prices.index.name = "timestamp"
        segment_prices.sort_index(inplace=True)




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

            for period, delta, timeframe in period_timdelta_timeframe:

                analytics_snapshots = self.get_analytics_snapshots(
                    period=period,
                    delta=delta,
                    current_datetime=current_datetime,
                    model_portfolio_snapshots=model_portfolio_snapshots
                )
                full_segment_prices_df = pd.DataFrame()
                self.get_stock_prices_at_snapshot_changes(
                    segment_prices=full_segment_prices_df,
                    analytics_snapshots=analytics_snapshots
                )
                if full_segment_prices_df.empty:
                    continue



                for index, analytics_snapshot in enumerate(analytics_snapshots):
                    segment_start = analytics_snapshot.timestamp
                    segment_end = (
                        analytics_snapshots[index + 1].timestamp
                        if index + 1 < len(analytics_snapshots)
                        else current_datetime
                    )
                    symbols = [position.symbol for position in analytics_snapshot.positions]
                    segment_prices = self.alpaca_broker_client.get_stock_prices_over_time(
                        symbols=symbols,
                        start_datetime=segment_start,
                        end_datetime=segment_end,
                        timeframe=timeframe,
                    )
                    full_segment_prices_df = (
                        full_segment_prices_df
                        .combine_first(segment_prices)
                    )
                full_segment_prices_df = full_segment_prices_df.sort_index()

                cumulative_return_frames: List[pd.DataFrame] = []
                portfolio_value_at_segment_start = 1.0

                for index, analytics_snapshot in enumerate(analytics_snapshots):
                    segment_start = analytics_snapshot.timestamp
                    segment_end = (
                        analytics_snapshots[index + 1].timestamp
                        if index + 1 < len(analytics_snapshots)
                        else current_datetime
                    )
                    active_symbols = [
                        position.symbol
                        for position in analytics_snapshot.positions
                    ]
                    segment_mask = (
                        (full_segment_prices_df.index >= segment_start)
                        & (full_segment_prices_df.index <= segment_end)
                    )
                    simulation_prices = (
                        full_segment_prices_df.loc[segment_mask, active_symbols]
                        .sort_index()
                        .ffill()
                        .dropna(subset=active_symbols)
                    )
                    if simulation_prices.empty:
                        raise ModelPortfolioAnalyticsServiceError(
                            message=(
                                "No complete price data available for model "
                                f"portfolio '{portfolio_id}' between "
                                f"'{segment_start.isoformat()}' and "
                                f"'{segment_end.isoformat()}'"
                            ),
                            code="MODEL_PORTFOLIO_ANALYTICS_PRICE_DATA_MISSING",
                        )

                    starting_prices = simulation_prices.iloc[0]
                    segment_return = pd.Series(
                        0.0,
                        index=simulation_prices.index,
                        dtype=float,
                    )
                    for position in analytics_snapshot.positions:
                        symbol_return = (
                            simulation_prices[position.symbol]
                            / starting_prices[position.symbol]
                        ) - 1.0
                        segment_return += (
                            position.current_weight
                            * position.direction
                            * position.leverage
                            * symbol_return
                        )

                    segment_portfolio_values = (
                        portfolio_value_at_segment_start
                        * (1.0 + segment_return)
                    )
                    segment_frame = pd.DataFrame(
                        {
                            "cumulative_returns": (
                                segment_portfolio_values - 1.0
                            ) * 100.0
                        }
                    )
                    if cumulative_return_frames:
                        segment_frame = segment_frame.iloc[1:]
                    if not segment_frame.empty:
                        cumulative_return_frames.append(segment_frame)

                    portfolio_value_at_segment_start = float(
                        segment_portfolio_values.iloc[-1]
                    )

                cumulative_returns_df = (
                    pd.concat(cumulative_return_frames).sort_index()
                    if cumulative_return_frames
                    else pd.DataFrame(columns=["cumulative_returns"])
                )
                period_metrics = self.calculate_period_metrics(
                    cumulative_returns_df=cumulative_returns_df,
                    analytics_snapshots=analytics_snapshots,
                    timeframe=timeframe,
                )
                print(period_metrics)
                response[period] = {
                    "timeframe": timeframe,
                    "timestamp": [
                        timestamp.isoformat()
                        for timestamp in cumulative_returns_df.index
                    ],
                    "cumulative_returns": cumulative_returns_df[
                        "cumulative_returns"
                    ].tolist(),
                    **period_metrics,
                }






            return response

        except ModelPortfolioAnalyticsServiceError:
            raise
        except AlpacaBrokerClientError as e:
            raise ModelPortfolioAnalyticsServiceError(
                message=f"Failed to get model portfolio price bars for portfolio '{portfolio_id}': {e}",
                code="MODEL_PORTFOLIO_ANALYTICS_GET_BARS_FAILED",
            ) from e
        except Exception as e:
            raise ModelPortfolioAnalyticsServiceError(
                message=f"Failed to calculate model portfolio bars for portfolio '{portfolio_id}': {e}",
                code="MODEL_PORTFOLIO_ANALYTICS_GET_BARS_FAILED",
            ) from e
