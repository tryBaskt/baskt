# backend/services/backtest_service.py

from __future__ import annotations
from typing import Any, Dict, List, Optional, TypeAlias
import pandas as pd
from domain.backtest import BacktestPosition
from clients.yfinance_client import YFinanceClient, YFinanceClientError
from clients.alpaca_broker_client import AlpacaBrokerClient, AlpacaBrokerClientError
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
        yfinance_client: YFinanceClient, 
        alpaca_broker_client: AlpacaBrokerClient,
        periods_per_year: int = 252
    ) -> None:
        """
        Initialize the backtest service.

        Args:
            yfinance_client: Market data client used to fetch historical price
                series.
            alpaca_broker_client: Alpaca client used to fetch tradable Baskt
                assets.
            periods_per_year: Number of return periods in one year (252 for trading days).

        Returns:
            None.
        """
        self.market_data = yfinance_client
        self.periods_per_year = periods_per_year
        self.alpaca_broker_client = alpaca_broker_client


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
                weight as a fraction or target_weight as a percent/fraction.
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


        # 1) Build domain positions with time series
        positions: List[BacktestPosition] = []
        for p in positions_conf:
            try:
                sym = str(p["symbol"]).upper()
                raw_weight = p["weight"] if p.get("weight") is not None else p["target_weight"]
                weight = float(raw_weight)
                if abs(weight) > 1:
                    weight = weight / 100.0
                direction = int(p["direction"])
                if direction not in {-1, 1}:
                    raise ValueError("direction must be 1 for long or -1 for short")
                leverage = float(p.get("leverage", 1.0))
                ts = self.market_data.fetch_history(sym, start_date, end_date)
            except KeyError as e:
                raise BacktestServiceValidationError(
                    f"Missing required position field: {e}"
                )
            except (TypeError, ValueError) as e:
                raise BacktestServiceValidationError(
                    f"Invalid position configuration for symbol '{p.get('symbol', 'UNKNOWN')}': {e}"
                )
            except YFinanceClientError as e:
                raise BacktestServiceDataError(
                    f"Failed to fetch market data for symbol '{p.get('symbol', 'UNKNOWN')}': {e}"
                )

            if ts is None or ts.empty:
                continue

            positions.append(
                BacktestPosition(
                    symbol=sym,
                    time_series=ts,
                    weight=weight,
                    direction=direction,
                    leverage=leverage,
                )
            )

        if not positions:
            raise BacktestServiceDataError("No price data available for the selected positions")
        
        # 2) Portfolio daily returns
        portfolio_daily_ret = self._simulate_portfolio_daily_returns(
            positions=positions, 
            price_col=price_col
        )

        # 3) Metrics + cumulative return series (cropped to date range)
        cum_ret_series, metrics = self._calculate_backtest_metrics(
            positions=positions,
            daily_ret=portfolio_daily_ret,
            backtest_start_date=start_date,
            backtest_end_date=end_date,
        )

        return {
            "dates": [d.strftime("%Y-%m-%d") for d in cum_ret_series.index],
            "cumulative_returns": [float(x) for x in cum_ret_series.values],
            "metrics": metrics,
        }


    def _simulate_portfolio_daily_returns(
        self,
        *,
        positions: List[BacktestPosition],
        price_col: str = "close",
    ) -> pd.Series:
        """
        Compute portfolio daily returns by aligning all position series on common dates.

        Args:
            positions: Domain positions with historical time series and exposure settings.
            price_col: Price column used to compute percentage returns.

        Returns:
            pd.Series: Aggregated daily portfolio returns indexed by date.

        Raises:
            BacktestServiceValidationError: If positions is empty.
            BacktestServiceCalculationError: If symbols have no overlapping dates.
        """
        if not positions:
            raise BacktestServiceValidationError("positions list is empty")

        # Common dates intersection
        date_sets = [set(pos.time_series.index) for pos in positions]
        common_dates = set.intersection(*date_sets)
        if not common_dates:
            raise BacktestServiceCalculationError("No overlapping dates across provided positions")

        common_index = pd.DatetimeIndex(sorted(common_dates))
        component_returns = pd.DataFrame(index=common_index)

        for pos in positions:
            df = pos.time_series.copy()
            df = df.sort_index()
            df.index = pd.to_datetime(df.index)

            df = df.reindex(common_index)
            prices = df[price_col].astype(float)

            rets = prices.pct_change().fillna(0.0)
            weighted_rets = rets * pos.weight * pos.direction * pos.leverage

            component_returns[pos.symbol] = weighted_rets

        portfolio_returns = component_returns.sum(axis=1)
        return portfolio_returns


    def _calculate_backtest_metrics(
        self,
        *,
        positions: List[BacktestPosition],
        daily_ret: pd.Series,
        backtest_start_date: str,
        backtest_end_date: str,
    ) -> tuple[pd.Series, BacktestMetricsDict]:
        """
        Calculate cumulative return series and summary metrics for a backtest slice.

        Args:
            positions: Portfolio positions used to derive leverage-adjusted direction tilt.
            daily_ret: Portfolio daily return series.
            backtest_start_date: Inclusive start date for slicing the return series.
            backtest_end_date: Inclusive end date for slicing the return series.

        Returns:
            A tuple of:
                - sliced_cum: pd.Series of cumulative returns (starting at 0)
                - metrics: dict containing final cumulative return, CAGR,
                  leverage_adjusted_direction, and annualized_volatility

        Raises:
            BacktestServiceCalculationError: If the sliced return series is
            empty.
        """
        sliced_ret = daily_ret.loc[backtest_start_date:backtest_end_date]

        if sliced_ret.empty:
            raise BacktestServiceCalculationError("Backtest slice returned empty data")

        sliced_cum = (1 + sliced_ret).cumprod() - 1

        # Final cumulative return
        total_return = float(sliced_cum.iloc[-1])

        # CAGR
        n_periods = len(sliced_ret)
        cagr = (1.0 + total_return) ** (self.periods_per_year / n_periods) - 1.0 if n_periods > 0 else None

        # Leverage adjusted Direction Tilt
        leverage_adjusted_direction = float(
            sum(float(pos.weight) * int(pos.direction) * float(pos.leverage) for pos in positions)
        )

        # Annualized volatility
        annualized_volatility_raw = sliced_ret.std(ddof=1) * (self.periods_per_year ** 0.5)
        annualized_volatility = None if pd.isna(annualized_volatility_raw) else float(annualized_volatility_raw)

        # Store metrics
        metrics: BacktestMetricsDict = {
            "final_cumulative_return": float(total_return),
            "cagr": float(cagr) if cagr is not None else None,
            "leverage_adjusted_direction": leverage_adjusted_direction,
            "annualized_volatility": annualized_volatility,
        }

        return sliced_cum, metrics
