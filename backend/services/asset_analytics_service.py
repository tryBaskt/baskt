"""Shared portfolio-performance simulation for asset analytics services."""

from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Literal, Optional

import pandas as pd
from alpaca.trading.models import Calendar

from clients.alpaca_broker_client import AlpacaBrokerClient, AlpacaBrokerClientError
from clients.vectorbt_client import VectorBTClient, VectorBTClientError
from clients.yfinance_client import YFinanceClient, YFinanceClientError
from domain.vectorbt_domain import VectorBTPortfolioAnalytics


class AssetAnalyticsServiceError(Exception):
    """Raised when shared asset performance simulation fails."""

    def __init__(
        self,
        message: str,
        code: str = "ASSET_ANALYTICS_SERVICE_ERROR",
    ) -> None:
        """Initialize an asset analytics service exception.

        Args:
            message: Human-readable failure details.
            code: Stable application error code identifying the failure.

        Returns:
            None.
        """
        super().__init__(message)
        self.code = code


class AssetAnalyticsService:
    """Run performance simulations shared by asset analytics workflows."""

    def __init__(
        self,
        *,
        alpaca_broker_client: AlpacaBrokerClient,
        yfinance_client: YFinanceClient,
        vectorbt_client: VectorBTClient,
    ) -> None:
        """Initialize the shared analytics service.

        Args:
            alpaca_broker_client: Client used for recent and point-in-time
                market data.
            yfinance_client: Client used for long-range historical data.
            vectorbt_client: Client used for portfolio simulations.

        Returns:
            None.
        """
        self.alpaca_broker_client = alpaca_broker_client
        self.yfinance_client = yfinance_client
        self.vectorbt_client = vectorbt_client

    def get_market_calendar(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> List[Calendar]:
        """Get Alpaca stock-market sessions for an inclusive date range.

        Args:
            start_date: Inclusive first calendar date.
            end_date: Inclusive last calendar date.

        Returns:
            List[Calendar]: Alpaca market-calendar sessions.

        Raises:
            AssetAnalyticsServiceError: If Alpaca cannot return the calendar.
        """
        try:
            return self.alpaca_broker_client.get_stock_market_calendar(
                start_date=start_date,
                end_date=end_date,
            )
        except AlpacaBrokerClientError as error:
            raise AssetAnalyticsServiceError(
                message=f"Failed to get stock market calendar: {error}",
                code="ASSET_ANALYTICS_MARKET_CALENDAR_FAILED",
            ) from error

    def get_prices_at_time(
        self,
        *,
        symbols: List[str],
        timestamp: datetime,
    ) -> Dict[str, float]:
        """Get Alpaca prices at or immediately before a timestamp.

        Args:
            symbols: Stock symbols to price.
            timestamp: Timezone-aware target timestamp.

        Returns:
            Dict[str, float]: Price keyed by symbol.

        Raises:
            AssetAnalyticsServiceError: If Alpaca cannot return prices.
        """
        try:
            return self.alpaca_broker_client.get_stock_prices_at_time(
                symbols=symbols,
                timestamp=timestamp,
            )
        except AlpacaBrokerClientError as error:
            raise AssetAnalyticsServiceError(
                message=f"Failed to get prices at '{timestamp}': {error}",
                code="ASSET_ANALYTICS_POINT_IN_TIME_PRICES_FAILED",
            ) from error

    def get_prices_over_time(
        self,
        *,
        symbols: List[str],
        start_datetime: datetime,
        end_datetime: datetime,
        timeframe: str,
        source: Literal["alpaca", "yfinance"] = "alpaca",
    ) -> pd.DataFrame:
        """Get a UTC timestamp-by-symbol close-price DataFrame.

        Args:
            symbols: Stock symbols to fetch.
            start_datetime: Inclusive timezone-aware start timestamp.
            end_datetime: Exclusive timezone-aware end timestamp.
            timeframe: Requested price-bar timeframe.
            source: Market-data provider, either ``alpaca`` or ``yfinance``.

        Returns:
            pd.DataFrame: UTC timestamps as rows and symbols as columns.

        Raises:
            AssetAnalyticsServiceError: If the source is unsupported or its
                client cannot return prices.
        """
        try:
            if source == "alpaca":
                return self.alpaca_broker_client.get_stock_prices_over_time(
                    symbols=symbols,
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                    timeframe=timeframe,
                )
            if source == "yfinance":
                return self.yfinance_client.get_stock_prices_over_time(
                    symbols=symbols,
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                    timeframe=timeframe,
                )
            raise AssetAnalyticsServiceError(
                message=f"Unsupported asset price source '{source}'",
                code="ASSET_ANALYTICS_PRICE_SOURCE_UNSUPPORTED",
            )
        except AssetAnalyticsServiceError:
            raise
        except (AlpacaBrokerClientError, YFinanceClientError) as error:
            raise AssetAnalyticsServiceError(
                message=(
                    f"Failed to get prices from '{source}' for symbols "
                    f"{symbols}: {error}"
                ),
                code="ASSET_ANALYTICS_PRICES_OVER_TIME_FAILED",
            ) from error


    def calculate_portfolio_analytics(
        self,
        *,
        prices: pd.DataFrame,
        target_exposure: pd.DataFrame,
        frequency: str,
        initial_cash: float = 10_000.0,
        fees: float = 0.0,
        slippage: float = 0.0,
        benchmark_returns: Optional[pd.Series] = None,
    ) -> VectorBTPortfolioAnalytics:
        """Calculate performance for static or changing target exposures.

        Each non-null target-exposure row must contain the complete desired
        exposure for every real asset at that rebalance timestamp. Positive
        values are long exposure and negative values are short exposure. This
        method adds the synthetic financing position required by VectorBT for
        leveraged portfolios.

        Args:
            prices: Complete price DataFrame indexed by timestamp with one
                column per real asset.
            target_exposure: DataFrame aligned with prices. Rebalance rows
                contain complete decimal target exposures; other rows are null.
            frequency: VectorBT-compatible frequency such as ``1d``, ``1h``,
                or ``5min``.
            initial_cash: Starting simulation cash.
            fees: Proportional transaction fees.
            slippage: Proportional execution slippage.
            benchmark_returns: Optional benchmark returns aligned to the
                simulation timestamps for alpha and beta.

        Returns:
            VectorBTPortfolioSimulation: Normalized simulation performance.

        Raises:
            AssetAnalyticsServiceError: If price and exposure shapes differ,
                no rebalance target exists, or VectorBT simulation fails.
        """
        if prices.empty or target_exposure.empty:
            raise AssetAnalyticsServiceError(
                message="Asset analytics prices and target exposure cannot be empty",
                code="ASSET_ANALYTICS_INPUT_EMPTY",
            )
        if not prices.index.equals(target_exposure.index):
            raise AssetAnalyticsServiceError(
                message="Asset analytics prices and target exposure indexes must match",
                code="ASSET_ANALYTICS_INDEX_MISMATCH",
            )
        if list(prices.columns) != list(target_exposure.columns):
            raise AssetAnalyticsServiceError(
                message="Asset analytics prices and target exposure columns must match",
                code="ASSET_ANALYTICS_COLUMNS_MISMATCH",
            )

        simulation_prices = prices.copy()
        simulation_target_exposure = target_exposure.copy()
        rebalance_timestamps = simulation_target_exposure.index[
            simulation_target_exposure.notna().any(axis=1)
        ]
        if rebalance_timestamps.empty:
            raise AssetAnalyticsServiceError(
                message="Asset analytics target exposure has no rebalance rows",
                code="ASSET_ANALYTICS_REBALANCE_TARGET_MISSING",
            )

        financing_symbol = "__BASKT_FINANCING__"
        simulation_prices[financing_symbol] = 1.0
        simulation_target_exposure[financing_symbol] = float("nan")
        for timestamp in rebalance_timestamps:
            exposures = target_exposure.loc[timestamp]
            if exposures.isna().any():
                raise AssetAnalyticsServiceError(
                    message=(
                        "Asset analytics rebalance row must contain every "
                        f"target exposure at '{timestamp}'"
                    ),
                    code="ASSET_ANALYTICS_REBALANCE_TARGET_INCOMPLETE",
                )
            long_exposure = float(exposures[exposures > 0].sum())
            short_exposure = float(abs(exposures[exposures < 0].sum()))
            simulation_target_exposure.loc[
                timestamp,
                financing_symbol,
            ] = -max(0.0, long_exposure - short_exposure - 1.0)

        try:
            return self.vectorbt_client.calculate_portfolio_analytics(
                prices=simulation_prices,
                target_exposure=simulation_target_exposure,
                frequency=frequency,
                initial_cash=initial_cash,
                fees=fees,
                slippage=slippage,
                excluded_direction_symbols=[financing_symbol],
                benchmark_returns=benchmark_returns,
            )
        except VectorBTClientError as error:
            raise AssetAnalyticsServiceError(
                message=f"Failed to calculate asset performance: {error}",
                code="ASSET_ANALYTICS_VECTORBT_FAILED",
            ) from error
