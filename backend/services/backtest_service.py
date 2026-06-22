# backend/services/backtest_service.py

from __future__ import annotations
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, TypeAlias
import pandas as pd
from domain.backtest import BacktestPosition
from clients.alpaca_broker_client import AlpacaBrokerClient, AlpacaBrokerClientError
from services.asset_analytics_service import (
    AssetAnalyticsService,
    AssetAnalyticsServiceError,
)
from domain.baskt import BasktAsset

BacktestMetricsDict: TypeAlias = Dict[str, Optional[float]]
BacktestRunResult: TypeAlias = Dict[str, List[str] | List[float] | BacktestMetricsDict]
BacktestPositionConfig: TypeAlias = Dict[str, Any]

class BacktestServiceError(Exception):
    """Base error for backtest service failures."""

    def __init__(self, message: str, code: str = "BACKTEST_SERVICE_ERROR") -> None:
        """
        Initialize a backtest service exception.

        Args:
            message: Human-readable error details.
            code: Stable error code identifying the failed operation.

        Returns:
            None.
        """
        super().__init__(message)
        self.code = code


class BacktestServiceValidationError(BacktestServiceError):
    def __init__(self, message: str) -> None:
        """
        Initialize a backtest validation exception.

        Args:
            message: Human-readable validation details.

        Returns:
            None.
        """
        super().__init__(message=message, code="BACKTEST_SERVICE_VALIDATION_ERROR")


class BacktestServiceDataError(BacktestServiceError):
    def __init__(self, message: str) -> None:
        """
        Initialize a backtest market-data exception.

        Args:
            message: Human-readable data retrieval details.

        Returns:
            None.
        """
        super().__init__(message=message, code="BACKTEST_SERVICE_DATA_ERROR")


class BacktestServiceCalculationError(BacktestServiceError):
    def __init__(self, message: str) -> None:
        """
        Initialize a backtest calculation exception.

        Args:
            message: Human-readable calculation failure details.

        Returns:
            None.
        """
        super().__init__(message=message, code="BACKTEST_SERVICE_CALCULATION_ERROR")


class BacktestService:
    """Service layer for building and evaluating a basket backtest."""

    def __init__(
        self, 
        *, 
        alpaca_broker_client: AlpacaBrokerClient,
        asset_analytics_service: AssetAnalyticsService,
    ) -> None:
        """
        Initialize the backtest service.

        Args:
            alpaca_broker_client: Alpaca client used to fetch tradable Baskt
                assets.
            asset_analytics_service: Shared service used to simulate portfolio
                performance and calculate metrics.

        Returns:
            None.
        """
        self.alpaca_broker_client = alpaca_broker_client
        self.asset_analytics_service = asset_analytics_service


    def get_tradeable_fractionable_US_baskt_assets(
        self
    ) -> List[BasktAsset]:
        """
        Get active US equity assets that can be traded fractionally in Baskt.

        Args:
            None.

        Returns:
            List[BasktAsset]: Tradable, fractionable US equity assets.

        Raises:
            BacktestServiceError: If Alpaca fails while fetching assets.
        """
        try:
            assets = self.alpaca_broker_client.get_tradeable_fractionable_US_assets()
            baskt_assets = [
                BasktAsset(
                    symbol=asset.symbol,
                    tradable=asset.tradable,
                    fractionable=asset.fractionable,
                    shortable=asset.shortable,
                    asset_id=str(asset.id),
                    asset_class=str(getattr(asset.asset_class, "name", asset.asset_class))
                )
                for asset in assets
            ]
            return baskt_assets
        except AlpacaBrokerClientError as err:
            raise BacktestServiceError(
                message=f"Failed to get tradeable, fractionable, US baskt assets: {err}",
                code="BACKTEST_GET_TRADEABLE_FRACTIONABLE_US_BASKT_ASSETS_FAILED"
            ) from err


    def run_backtest(
        self,
        *,
        start_date: str,
        end_date: str,
        positions_conf: List[BacktestPositionConfig],
        price_col: str = "close",
    ) -> BacktestRunResult:
        """
        Run a backtest for the given portfolio configuration and date window.

        Args:
            start_date: Inclusive start date in ISO format (YYYY-MM-DD).
            end_date: Inclusive end date in ISO format (YYYY-MM-DD).
            positions_conf: List of input position dictionaries. Each entry
                should include symbol, direction, optional leverage, and either
                weight or target_weight as a decimal fraction from 0 to 1.
            price_col: Price column to use from historical bars (default: "close").

        Returns:
            BacktestRunResult: Dictionary containing dates, cumulative_returns,
            and metrics.

        Raises:
            BacktestServiceValidationError: If the position configuration is
            missing required fields or contains invalid values.
            BacktestServiceDataError: If market data cannot be fetched or no
            usable price data exists.
            BacktestServiceCalculationError: If returns or metrics cannot be
            calculated for the requested date range.
        """
        if not positions_conf:
            raise BacktestServiceValidationError("At least one position is required")
        if price_col.lower() != "close":
            raise BacktestServiceValidationError(
                "Only the 'close' price column is supported"
            )

        # Build and validate position metadata before fetching prices once.
        positions: List[BacktestPosition] = []
        for p in positions_conf:
            try:
                sym = str(p["symbol"]).upper()
                raw_weight = p["weight"] if p.get("weight") is not None else p["target_weight"]
                weight = float(raw_weight)
                direction = int(p["direction"])
                if direction not in {-1, 1}:
                    raise ValueError("direction must be 1 for long or -1 for short")
                leverage = float(p.get("leverage", 1.0))
            except KeyError as e:
                raise BacktestServiceValidationError(
                    f"Missing required position field: {e}"
                )
            except (TypeError, ValueError) as e:
                raise BacktestServiceValidationError(
                    f"Invalid position configuration for symbol '{p.get('symbol', 'UNKNOWN')}': {e}"
                )
            positions.append(
                BacktestPosition(
                    symbol=sym,
                    weight=weight,
                    direction=direction,
                    leverage=leverage,
                )
            )

        try:
            start_datetime = datetime.combine(
                date.fromisoformat(start_date),
                time.min,
                tzinfo=timezone.utc,
            )
            end_datetime = datetime.combine(
                date.fromisoformat(end_date),
                time.min,
                tzinfo=timezone.utc,
            ) + timedelta(days=1)
        except ValueError as error:
            raise BacktestServiceValidationError(
                "start_date and end_date must use YYYY-MM-DD format"
            ) from error

        if end_datetime <= start_datetime:
            raise BacktestServiceValidationError(
                "end_date must be on or after start_date"
            )

        symbols = [position.symbol for position in positions]
        try:
            prices = self.asset_analytics_service.get_prices_over_time(
                symbols=symbols,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                timeframe="1D",
                source="yfinance",
            )
        except AssetAnalyticsServiceError as error:
            raise BacktestServiceDataError(
                f"Failed to fetch backtest market data: {error}"
            ) from error

        missing_symbols = [symbol for symbol in symbols if symbol not in prices.columns]
        if missing_symbols:
            raise BacktestServiceDataError(
                f"Price data is missing for symbols {missing_symbols}"
            )

        prices = prices.loc[:, symbols].dropna()
        if prices.empty:
            raise BacktestServiceDataError(
                "No overlapping price data is available for the selected positions"
            )

        target_exposure = pd.DataFrame(
            float("nan"),
            index=prices.index,
            columns=prices.columns,
            dtype=float,
        )
        first_timestamp = prices.index[0]
        target_exposure.loc[first_timestamp, :] = 0.0
        for position in positions:
            exposure = position.weight * position.direction * position.leverage
            target_exposure.loc[first_timestamp, position.symbol] = exposure

        try:
            simulation_result = self.asset_analytics_service.calculate_performance(
                prices=prices,
                target_exposure=target_exposure,
                frequency="1d",
                initial_cash=10_000.0,
                fees=0.0,
                slippage=0.0,
            )
        except AssetAnalyticsServiceError as error:
            raise BacktestServiceCalculationError(
                f"Failed to calculate backtest performance: {error}"
            ) from error

        metrics: BacktestMetricsDict = {
            "final_cumulative_return": (
                simulation_result.final_cumulative_return
            ),
            "cagr": simulation_result.cagr,
            "leverage_adjusted_direction": (
                simulation_result.leverage_adjusted_direction
            ),
            "annualized_volatility": (
                simulation_result.annualized_volatility
            ),
        }
        return {
            "dates": [
                timestamp.strftime("%Y-%m-%d")
                for timestamp in simulation_result.timestamps
            ],
            "cumulative_returns": simulation_result.cumulative_returns,
            "metrics": metrics,
        }
