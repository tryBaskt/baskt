# backend/services/model_portfolio_analytics_service.py

# Python imports
from __future__ import annotations
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta, date
from math import sqrt
from collections import defaultdict

# Baskt imports
from clients.alpaca_broker_client import AlpacaBrokerClient, AlpacaBrokerClientError
from domain.model_portfolio import ModelPortfolioSnapshot
from repository.model_portfolio_repository import ModelPortfolioRepository
from domain.model_portfolio_analytics import ModelPortfolioAnalyticsPosition, ModelPortfolioAnalyticsSnapshot

# import pandas
import pandas as pd


class ModelPortfolioAnalyticsServiceError(Exception):
	def __init__(self, message: str, code: str = "ACCOUNT_ANALYTICS_SERVICE_ERROR") -> None:
		"""
		Initialize an account analytics service exception.

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
    ):
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


    def get_model_portfolio_bars(
        self,
        portfolio_id: str,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get model portfolio cumulative return series for standard periods.

        Args:
            portfolio_id: Identifier of the model portfolio to analyze.

        Returns:
            Dict[str, Dict[str, Any]]: Five period return series keyed by 1D,
            1W, 1M, 3M, and 1A. Each period contains timeframe, timestamp,
            cumulative_returns, total_cumulative_return, cagr,
            annualized_volatility, and leverage_adjusted_direction.

        Raises:
            ModelPortfolioAnalyticsServiceError: If portfolio history cannot be
            loaded, Alpaca price bars cannot be fetched, or any unexpected error
            occurs while calculating returns.
        """

        try:

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

            current_datetime = datetime.now(timezone.utc)
            for period, delta, timeframe in period_timdelta_timeframe:

                # Create analytics snapshots per period
                current_period_start = current_datetime - delta
                if period == "1D":
                    current_period_start = datetime.combine(
                        date.today(),
                        datetime.min.time().replace(hour=14, minute=30, second=0, microsecond=0),
                        tzinfo=timezone.utc,
                    )
                if period == "all":
                    current_period_start = model_portfolio_snapshots[0].timestamp.replace(second=0, microsecond=0)

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

                # Create dataframe of timestamps with columns of stocks
                length_analytics_snapshots = len(analytics_snapshots)
                all_analytics_snapshots_df = pd.DataFrame()
                for i in range(length_analytics_snapshots):
                    analytics_snapshot = analytics_snapshots[i]
                    start_timestamp = analytics_snapshot.timestamp
                    end_timestamp = current_datetime

                    if i < length_analytics_snapshots-1:
                        end_timestamp = (analytics_snapshots[i + 1].timestamp - timedelta(minutes=1)).replace(second=0, microsecond=0)

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

                # Create dataframe of timestamps and cumulative returns
                cumulative_return_frames: List[pd.DataFrame] = []
                segment_base_value = 1.0
                for i in range(length_analytics_snapshots):
                    analytics_snapshot = analytics_snapshots[i]
                    active_symbols = [position.symbol for position in analytics_snapshot.positions]
                    segment_start_timestamp = analytics_snapshot.timestamp
                    segment_end_timestamp = current_datetime

                    if i < length_analytics_snapshots - 1:
                        segment_end_timestamp = (
                            analytics_snapshots[i + 1].timestamp
                            - timedelta(minutes=1)
                        ).replace(second=0, microsecond=0)

                    segment_prices_df = all_analytics_snapshots_df.loc[
                        (all_analytics_snapshots_df.index >= segment_start_timestamp)
                        & (all_analytics_snapshots_df.index <= segment_end_timestamp),
                        active_symbols,
                    ].ffill()
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

                response[period] = {
                    "timeframe": timeframe,
                    "timestamp": [
                        timestamp.isoformat()
                        for timestamp in cumulative_returns_df.index
                    ],
                    "cumulative_returns": cumulative_returns_df["cumulative_returns"].tolist()
                }

            return response
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
