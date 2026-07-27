# backend/services/backtest_analytics_service.py

from __future__ import annotations
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, TypeAlias
import pandas as pd
from domain.backtest_domain import BacktestPosition
from clients.alpaca_broker_client import AlpacaBrokerClient, AlpacaBrokerClientError
from services.asset_analytics_service import (
    AssetAnalyticsService,
    AssetAnalyticsInternalServerError,
)
from domain.stock_domain import Stock

BacktestRunResult: TypeAlias = Dict[str, str | List[float] | Optional[float]]
BacktestPositionConfig: TypeAlias = Dict[str, Any]

class BacktestInternalServerError(Exception):
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


class BacktestServiceValidationError(BacktestInternalServerError):
    def __init__(self, message: str) -> None:
        """
        Initialize a backtest validation exception.

        Args:
            message: Human-readable validation details.

        Returns:
            None.
        """
        super().__init__(message=message, code="BACKTEST_SERVICE_VALIDATION_ERROR")


class BacktestServiceDataError(BacktestInternalServerError):
    def __init__(self, message: str) -> None:
        """
        Initialize a backtest market-data exception.

        Args:
            message: Human-readable data retrieval details.

        Returns:
            None.
        """
        super().__init__(message=message, code="BACKTEST_SERVICE_DATA_ERROR")


class BacktestServiceCalculationError(BacktestInternalServerError):
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
    ) -> List[Stock]:
        """
        Get active US equity assets that can be traded fractionally in Baskt.

        Args:
            None.

        Returns:
            List[Stock]: Tradable, fractionable US equity assets.

        Raises:
            BacktestInternalServerError: If Alpaca fails while fetching assets.
        """
        try:
            assets = self.alpaca_broker_client.get_tradeable_fractionable_US_assets()
            stocks = [
                Stock(
                    symbol=asset.symbol,
                    tradable=asset.tradable,
                    fractionable=asset.fractionable,
                    shortable=asset.shortable,
                    marginable=asset.marginable,
                    stock_id=str(asset.id),
                    stock_class=str(getattr(asset.asset_class, "name", asset.asset_class))
                )
                for asset in assets
            ]
            return stocks
        except AlpacaBrokerClientError as err:
            raise BacktestInternalServerError(
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
        benchmark_symbol = "SPY"
        market_data_symbols = list(dict.fromkeys([*symbols, benchmark_symbol]))
        try:
            prices = self.asset_analytics_service.get_prices_over_time(
                symbols=market_data_symbols,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                timeframe="1D",
                source="yfinance",
            )
        except AssetAnalyticsInternalServerError as error:
            raise BacktestServiceDataError(
                f"Failed to fetch backtest market data: {error}"
            ) from error

        missing_symbols = [
            symbol for symbol in market_data_symbols if symbol not in prices.columns
        ]
        if missing_symbols:
            raise BacktestServiceDataError(
                f"Price data is missing for symbols {missing_symbols}"
            )

        prices = prices.loc[:, market_data_symbols].dropna()
        if prices.empty:
            raise BacktestServiceDataError(
                "No overlapping price data is available for the selected positions"
            )

        benchmark_returns = prices[benchmark_symbol].pct_change()
        portfolio_prices = prices.loc[:, symbols]
        target_exposure = pd.DataFrame(
            float("nan"),
            index=portfolio_prices.index,
            columns=portfolio_prices.columns,
            dtype=float,
        )
        first_timestamp = portfolio_prices.index[0]
        target_exposure.loc[first_timestamp, :] = 0.0
        for position in positions:
            exposure = position.weight * position.direction * position.leverage
            target_exposure.loc[first_timestamp, position.symbol] = exposure

        try:
            simulation_result = self.asset_analytics_service.calculate_portfolio_analytics(
                prices=portfolio_prices,
                target_exposure=target_exposure,
                frequency="1d",
                initial_cash=10_000.0,
                fees=0.0,
                slippage=0.0,
                benchmark_returns=benchmark_returns,
            )
        except AssetAnalyticsInternalServerError as error:
            raise BacktestServiceCalculationError(
                f"Failed to calculate backtest performance: {error}"
            ) from error

        return {
            "start_date": start_date,
            "end_date": end_date,
            "timestamps": simulation_result.timestamps,
            "cumulative_returns": simulation_result.cumulative_returns,
            "final_cumulative_return": simulation_result.final_cumulative_return,
            "cagr": simulation_result.cagr,
            "leverage_adjusted_direction": simulation_result.leverage_adjusted_direction,
            "annualized_volatility": simulation_result.annualized_volatility,
            "alpha": simulation_result.alpha,
            "beta": simulation_result.beta,
            "sharpe_ratio": simulation_result.sharpe_ratio,
            "maximum_drawdown": simulation_result.maximum_drawdown,
            "maximum_drawdown_duration": simulation_result.maximum_drawdown_duration,
        }
