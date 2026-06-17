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


    def _ensure_utc(self, value: datetime) -> datetime:
        """
        Normalize a datetime to UTC.

        Args:
            value: Datetime value to normalize.

        Returns:
            datetime: Timezone-aware UTC datetime.
        """
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _get_period_snapshots(
        self,
        *,
        snapshots: List[ModelPortfolioSnapshot],
        period_start: datetime,
    ) -> List[ModelPortfolioSnapshot]:
        """
        Get snapshots needed to calculate one period of returns.

        Args:
            snapshots: Full model portfolio position history.
            period_start: Start datetime for the requested return period.

        Returns:
            List[ModelPortfolioSnapshot]: The snapshot active at period_start
            followed by snapshots created during the period.
        """
        sorted_snapshots = sorted(
            snapshots,
            key=lambda snapshot: self._ensure_utc(snapshot.timestamp),
        )

        active_snapshot = None
        period_snapshots: List[ModelPortfolioSnapshot] = []
        for snapshot in sorted_snapshots:
            snapshot_timestamp = self._ensure_utc(snapshot.timestamp)
            if snapshot_timestamp <= period_start:
                active_snapshot = snapshot
            else:
                period_snapshots.append(snapshot)

        if active_snapshot is not None:
            return [active_snapshot] + period_snapshots

        return period_snapshots

    def _get_active_snapshot_index(
        self,
        *,
        snapshots: List[ModelPortfolioSnapshot],
        timestamp: datetime,
    ) -> int:
        """
        Find the snapshot active at a specific timestamp.

        Args:
            snapshots: Period snapshots sorted by timestamp.
            timestamp: Bar timestamp being evaluated.

        Returns:
            int: Index of the active snapshot.
        """
        active_index = 0
        for index, snapshot in enumerate(snapshots):
            if self._ensure_utc(snapshot.timestamp) <= timestamp:
                active_index = index
            else:
                break
        return active_index

    def _calculate_leverage_adjusted_direction(
        self,
        snapshot: ModelPortfolioSnapshot,
    ) -> float:
        """
        Calculate the portfolio's leverage-adjusted net direction.

        Args:
            snapshot: Model portfolio snapshot to evaluate.

        Returns:
            float: Sum of target_weight * direction * leverage for all positions.
        """
        return sum(
            position.target_weight * position.direction * position.leverage
            for position in snapshot.positions
        )

    def _calculate_annualized_volatility(
        self,
        *,
        cumulative_returns: List[float],
        timeframe: str,
    ) -> Optional[float]:
        """
        Calculate annualized volatility from cumulative return points.

        Args:
            cumulative_returns: Cumulative return values in percentage points.
            timeframe: Timeframe used for the return series.

        Returns:
            Optional[float]: Annualized volatility in percentage points, or None
            when there are not enough return points.
        """
        if len(cumulative_returns) < 3:
            return None

        period_returns = [
            (cumulative_returns[index] - cumulative_returns[index - 1]) / 100
            for index in range(1, len(cumulative_returns))
        ]
        mean_return = sum(period_returns) / len(period_returns)
        variance = sum(
            (period_return - mean_return) ** 2
            for period_return in period_returns
        ) / (len(period_returns) - 1)

        annualization_factor_by_timeframe = {
            "5Min": 252 * 78,
            "1H": 252 * 6.5,
            "1D": 252,
        }
        annualization_factor = annualization_factor_by_timeframe.get(timeframe, 252)
        return sqrt(variance) * sqrt(annualization_factor) * 100

    def _calculate_return_series(
        self,
        *,
        snapshots: List[ModelPortfolioSnapshot],
        bars_by_symbol: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, List[str] | List[float] | Optional[float]]:
        """
        Calculate cumulative model portfolio returns from bars and snapshots.

        Args:
            snapshots: Period snapshots sorted by timestamp.
            bars_by_symbol: Historical price bars keyed by symbol.

        Returns:
            Dict[str, List[str] | List[float] | Optional[float]]: Timestamp and
            cumulative return series plus derived metrics.
        """
        bar_prices_by_timestamp: Dict[datetime, Dict[str, float]] = {}
        for symbol, bars in bars_by_symbol.items():
            for bar in bars:
                timestamp = self._ensure_utc(bar["timestamp"])
                bar_prices_by_timestamp.setdefault(timestamp, {})[symbol] = bar["close"]

        timestamps = sorted(bar_prices_by_timestamp)
        latest_prices: Dict[str, float] = {}
        baseline_prices: Dict[str, float] = {}
        current_snapshot_index: Optional[int] = None
        segment_base_index = 1.0
        last_index: Optional[float] = None

        response_timestamps: List[str] = []
        cumulative_returns: List[float] = []

        for timestamp in timestamps:
            latest_prices.update(bar_prices_by_timestamp[timestamp])

            next_snapshot_index = self._get_active_snapshot_index(
                snapshots=snapshots,
                timestamp=timestamp,
            )
            active_snapshot = snapshots[next_snapshot_index]
            active_symbols = [position.symbol for position in active_snapshot.positions]

            if any(symbol not in latest_prices for symbol in active_symbols):
                continue

            if current_snapshot_index != next_snapshot_index:
                if last_index is not None:
                    segment_base_index = last_index
                current_snapshot_index = next_snapshot_index
                baseline_prices = {
                    symbol: latest_prices[symbol]
                    for symbol in active_symbols
                }

            if any(baseline_prices[symbol] == 0 for symbol in active_symbols):
                continue

            segment_return = sum(
                position.target_weight
                * position.direction
                * position.leverage
                * (
                    latest_prices[position.symbol]
                    / baseline_prices[position.symbol]
                    - 1
                )
                for position in active_snapshot.positions
            )
            last_index = segment_base_index * (1 + segment_return)

            response_timestamps.append(timestamp.isoformat())
            cumulative_returns.append((last_index - 1) * 100)

        total_cumulative_return = (
            cumulative_returns[-1]
            if cumulative_returns
            else None
        )

        return {
            "timestamp": response_timestamps,
            "cumulative_returns": cumulative_returns,
            "total_cumulative_return": total_cumulative_return,
        }

    def _calculate_cagr(
        self,
        *,
        timestamps: List[str],
        total_cumulative_return: Optional[float],
    ) -> Optional[float]:
        """
        Calculate CAGR for a cumulative return series.

        Args:
            timestamps: ISO timestamp values in the return series.
            total_cumulative_return: Final cumulative return in percentage
            points.

        Returns:
            Optional[float]: CAGR in percentage points, or None when it cannot
            be calculated.
        """
        if len(timestamps) < 2 or total_cumulative_return is None:
            return None

        start = datetime.fromisoformat(timestamps[0])
        end = datetime.fromisoformat(timestamps[-1])
        elapsed_years = (end - start).total_seconds() / (365.25 * 24 * 60 * 60)
        ending_value = 1 + (total_cumulative_return / 100)
        if elapsed_years <= 0 or ending_value <= 0:
            return None

        return ((ending_value ** (1 / elapsed_years)) - 1) * 100

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
        periods_and_timeframes = [
            ("1D", timedelta(days=1), "5Min"),
            ("1W", timedelta(weeks=1), "1H"),
            ("1M", timedelta(days=30), "1D"),
            ("3M", timedelta(days=90), "1D"),
            ("1A", timedelta(days=365), "1D"),
        ]

        try:
            snapshots = self.model_portfolio_repository.get_position_history(portfolio_id=portfolio_id)
            snapshots = sorted(
                snapshots,
                key=lambda snapshot: self._ensure_utc(snapshot.timestamp),
            )
            if not snapshots:
                return {}

            current_datetime = datetime.now(timezone.utc)
            first_snapshot_timestamp = self._ensure_utc(snapshots[0].timestamp)
            response: Dict[str, Dict[str, Any]] = {}

            for period_key, period_delta, timeframe in periods_and_timeframes:
                period_start = max(
                    current_datetime - period_delta,
                    first_snapshot_timestamp,
                )
                period_snapshots = self._get_period_snapshots(
                    snapshots=snapshots,
                    period_start=period_start,
                )
                if not period_snapshots:
                    response[period_key] = {
                        "timeframe": timeframe,
                        "timestamp": [],
                        "cumulative_returns": [],
                        "total_cumulative_return": None,
                        "cagr": None,
                        "annualized_volatility": None,
                        "leverage_adjusted_direction": None,
                    }
                    continue

                symbols = sorted({
                    position.symbol
                    for snapshot in period_snapshots
                    for position in snapshot.positions
                })
                bars_by_symbol = self.alpaca_broker_client.get_stock_price_bars(
                    symbols=symbols,
                    start=period_start,
                    end=current_datetime,
                    timeframe=timeframe,
                )
                period_response = self._calculate_return_series(
                    snapshots=period_snapshots,
                    bars_by_symbol=bars_by_symbol,
                )

                timestamp = period_response["timestamp"]
                cumulative_returns = period_response["cumulative_returns"]
                total_cumulative_return = period_response["total_cumulative_return"]
                response[period_key] = {
                    "timeframe": timeframe,
                    "timestamp": timestamp,
                    "cumulative_returns": cumulative_returns,
                    "total_cumulative_return": total_cumulative_return,
                    "cagr": self._calculate_cagr(
                        timestamps=timestamp,
                        total_cumulative_return=total_cumulative_return,
                    ),
                    "annualized_volatility": self._calculate_annualized_volatility(
                        cumulative_returns=cumulative_returns,
                        timeframe=timeframe,
                    ),
                    "leverage_adjusted_direction": self._calculate_leverage_adjusted_direction(
                        period_snapshots[-1]
                    ),
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

    def get_model_portfolio_bar(
        self,
        portfolio_id: str,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get model portfolio cumulative return series for standard periods.

        Args:
            portfolio_id: Identifier of the model portfolio to analyze.

        Returns:
            Dict[str, Dict[str, Any]]: Model portfolio bars keyed by period.

        Raises:
            ModelPortfolioAnalyticsServiceError: If the analytics calculation
            fails.
        """
        return self.get_model_portfolio_bars(portfolio_id=portfolio_id)
