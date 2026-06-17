from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd

from clients.yfinance_client import YFinanceClient, YFinanceClientError
from domain.model_portfolio import ModelPortfolioPosition, ModelPortfolioSnapshot
from repository.model_portfolio_repository import ModelPortfolioRepository


PerformancePeriod = Dict[str, List[str] | List[float] | Optional[float] | str]
ModelPortfolioPerformance = Dict[str, PerformancePeriod]


class ModelPortfolioPerformanceServiceError(Exception):
    """Raised when model portfolio performance cannot be calculated."""

    def __init__(self, message: str, code: str = "MODEL_PORTFOLIO_PERFORMANCE_ERROR"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _PeriodConfig:
    period: str
    timeframe: str
    yfinance_interval: str
    offset: pd.DateOffset
    periods_per_year: int


@dataclass(frozen=True)
class _SegmentResult:
    returns: pd.Series
    leverage_adjusted_direction: float


class ModelPortfolioPerformanceService:
    def __init__(
        self,
        *,
        y_finance_client: YFinanceClient,
        model_portfolio_repository: ModelPortfolioRepository,
    ):
        self.y_finance_client = y_finance_client
        self.model_portfolio_repository = model_portfolio_repository
        self.periods_and_timeframes = [
            _PeriodConfig("1D", "5Min", "5m", pd.DateOffset(days=1), 252 * 78),
            _PeriodConfig("1W", "1H", "1h", pd.DateOffset(weeks=1), 252 * 7),
            _PeriodConfig("1M", "1D", "1d", pd.DateOffset(months=1), 252),
            _PeriodConfig("3M", "1D", "1d", pd.DateOffset(months=3), 252),
            _PeriodConfig("1A", "1D", "1d", pd.DateOffset(years=1), 252),
        ]

    def get_model_portfolio_performance(
        self,
        portfolio_id: str,
    ) -> ModelPortfolioPerformance:
        """
        Calculate snapshot-aware model portfolio performance by period.

        Each returned period matches the account performance periods and
        timeframes: 1D/5Min, 1W/1H, 1M/1D, 3M/1D, and 1A/1D. Returns are
        calculated from the portfolio creation time forward, and each snapshot
        only affects performance from its timestamp until the next snapshot.

        Args:
            portfolio_id: Identifier of the model portfolio.

        Returns:
            ModelPortfolioPerformance: Dictionary keyed by period. Each period
            contains timestamp values, cumulative_returns percentage values,
            total_cumulative_return percentage, CAGR percentage, annualized
            volatility percentage, and leverage_adjusted_direction.

        Raises:
            ModelPortfolioPerformanceServiceError: If the portfolio has no
            snapshots or yfinance data cannot be fetched. Periods with no
            available return series are returned with empty graph arrays and
            None metrics.
            Any exception raised by ModelPortfolioRepository.get_model_portfolio
            if the portfolio cannot be loaded.
        """
        model_portfolio = self.model_portfolio_repository.get_model_portfolio(
            portfolio_id=portfolio_id
        )
        snapshots = sorted(
            model_portfolio.position_history,
            key=lambda snapshot: self._to_timestamp(snapshot.timestamp),
        )

        if not snapshots:
            raise ModelPortfolioPerformanceServiceError(
                message=f"Model portfolio '{portfolio_id}' has no position snapshots.",
                code="MODEL_PORTFOLIO_PERFORMANCE_NO_SNAPSHOTS",
            )

        created_at = self._to_timestamp(model_portfolio.created_at)
        now = pd.Timestamp.now(tz="UTC").tz_convert(None)
        performance: ModelPortfolioPerformance = {}

        for config in self.periods_and_timeframes:
            period_start = max(created_at, now - config.offset)
            period_result = self._calculate_period_performance(
                snapshots=snapshots,
                start_at=period_start,
                end_at=now,
                config=config,
            )
            performance[config.period] = period_result

        return performance

    def _calculate_period_performance(
        self,
        *,
        snapshots: List[ModelPortfolioSnapshot],
        start_at: pd.Timestamp,
        end_at: pd.Timestamp,
        config: _PeriodConfig,
    ) -> PerformancePeriod:
        segment_results: List[_SegmentResult] = []

        for index, snapshot in enumerate(snapshots):
            snapshot_start = self._to_timestamp(snapshot.timestamp)
            next_snapshot_start = (
                self._to_timestamp(snapshots[index + 1].timestamp)
                if index + 1 < len(snapshots)
                else end_at
            )

            segment_start = max(start_at, snapshot_start)
            segment_end = min(end_at, next_snapshot_start)

            if segment_start >= segment_end:
                continue

            segment_result = self._build_segment_returns(
                snapshot=snapshot,
                start_at=segment_start,
                end_at=segment_end,
                interval=config.yfinance_interval,
            )
            if not segment_result.returns.empty:
                segment_results.append(segment_result)

        if not segment_results:
            return self._empty_period(config)

        combined_returns = pd.concat(
            [segment.returns for segment in segment_results]
        ).sort_index()
        combined_returns = combined_returns[
            ~combined_returns.index.duplicated(keep="last")
        ]

        if combined_returns.empty:
            return self._empty_period(config)

        cumulative_returns = (1.0 + combined_returns).cumprod() - 1.0
        metrics = self._calculate_metrics(
            daily_returns=combined_returns,
            cumulative_returns=cumulative_returns,
            segment_results=segment_results,
            periods_per_year=config.periods_per_year,
        )

        return {
            "timeframe": config.timeframe,
            "timestamp": [self._format_timestamp(ts) for ts in cumulative_returns.index],
            "cumulative_returns": [
                float(round(value * 100.0, 6)) for value in cumulative_returns.values
            ],
            **metrics,
        }

    def _build_segment_returns(
        self,
        *,
        snapshot: ModelPortfolioSnapshot,
        start_at: pd.Timestamp,
        end_at: pd.Timestamp,
        interval: str,
    ) -> _SegmentResult:
        component_returns = pd.DataFrame()

        for position in snapshot.positions:
            try:
                history = self.y_finance_client.fetch_history(
                    ticker=position.symbol,
                    start_date=start_at.date().isoformat(),
                    end_date=end_at.date().isoformat(),
                    interval=interval,
                )
            except YFinanceClientError as err:
                raise ModelPortfolioPerformanceServiceError(
                    message=(
                        f"Failed to fetch performance data for symbol "
                        f"'{position.symbol}': {err}"
                    ),
                    code="MODEL_PORTFOLIO_PERFORMANCE_MARKET_DATA_FAILED",
                ) from err

            if history is None or history.empty or "close" not in history.columns:
                continue

            history = history.copy().sort_index()
            history.index = self._normalize_index(history.index)
            history = history.loc[
                (history.index >= start_at) & (history.index <= end_at)
            ]

            if history.empty:
                continue

            close_prices = history["close"].astype(float)
            weighted_returns = close_prices.pct_change().fillna(0.0)
            weighted_returns *= (
                self._normalize_weight(position)
                * int(position.direction)
                * float(position.leverage)
            )
            component_returns[str(position.symbol).upper()] = weighted_returns

        leverage_adjusted_direction = self._snapshot_leverage_adjusted_direction(
            snapshot=snapshot
        )

        if component_returns.empty:
            return _SegmentResult(
                returns=pd.Series(dtype=float),
                leverage_adjusted_direction=leverage_adjusted_direction,
            )

        component_returns = component_returns.dropna(how="any")
        if component_returns.empty:
            return _SegmentResult(
                returns=pd.Series(dtype=float),
                leverage_adjusted_direction=leverage_adjusted_direction,
            )

        return _SegmentResult(
            returns=component_returns.sum(axis=1),
            leverage_adjusted_direction=leverage_adjusted_direction,
        )

    def _calculate_metrics(
        self,
        *,
        daily_returns: pd.Series,
        cumulative_returns: pd.Series,
        segment_results: List[_SegmentResult],
        periods_per_year: int,
    ) -> Dict[str, Optional[float]]:
        total_return = float(cumulative_returns.iloc[-1])
        n_periods = len(daily_returns)
        cagr = (
            (1.0 + total_return) ** (periods_per_year / n_periods) - 1.0
            if n_periods > 0 and total_return > -1.0
            else None
        )
        annualized_volatility = (
            float(daily_returns.std(ddof=1) * (periods_per_year ** 0.5))
            if n_periods > 1
            else None
        )
        leverage_adjusted_direction = self._weighted_leverage_adjusted_direction(
            segment_results=segment_results
        )

        return {
            "total_cumulative_return": self._percent_or_none(total_return),
            "cagr": self._percent_or_none(cagr),
            "annualized_volatility": self._percent_or_none(annualized_volatility),
            "leverage_adjusted_direction": leverage_adjusted_direction,
        }

    def _weighted_leverage_adjusted_direction(
        self,
        *,
        segment_results: List[_SegmentResult],
    ) -> Optional[float]:
        total_points = sum(len(segment.returns) for segment in segment_results)
        if total_points == 0:
            return None

        weighted_sum = sum(
            segment.leverage_adjusted_direction * len(segment.returns)
            for segment in segment_results
        )
        return float(round(weighted_sum / total_points, 6))

    def _snapshot_leverage_adjusted_direction(
        self,
        *,
        snapshot: ModelPortfolioSnapshot,
    ) -> float:
        return float(
            sum(
                self._normalize_weight(position)
                * int(position.direction)
                * float(position.leverage)
                for position in snapshot.positions
            )
        )

    def _normalize_weight(self, position: ModelPortfolioPosition) -> float:
        weight = float(position.target_weight)
        return weight / 100.0 if abs(weight) > 1.0 else weight

    def _empty_period(self, config: _PeriodConfig) -> PerformancePeriod:
        return {
            "timeframe": config.timeframe,
            "timestamp": [],
            "cumulative_returns": [],
            "total_cumulative_return": None,
            "cagr": None,
            "annualized_volatility": None,
            "leverage_adjusted_direction": None,
        }

    def _percent_or_none(self, value: Optional[float]) -> Optional[float]:
        if value is None or pd.isna(value):
            return None
        return float(round(value * 100.0, 6))

    def _to_timestamp(self, value: Any) -> pd.Timestamp:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is not None:
            return timestamp.tz_convert("UTC").tz_localize(None)
        return timestamp

    def _normalize_index(self, index: pd.Index) -> pd.DatetimeIndex:
        timestamps = pd.DatetimeIndex(pd.to_datetime(index))
        if timestamps.tz is not None:
            timestamps = timestamps.tz_convert("UTC").tz_localize(None)
        return timestamps

    def _format_timestamp(self, timestamp: pd.Timestamp) -> str:
        if timestamp.hour == 0 and timestamp.minute == 0 and timestamp.second == 0:
            return timestamp.date().isoformat()
        return timestamp.isoformat()
