"""Client wrapper for normalized VectorBT portfolio simulations."""

from __future__ import annotations

from typing import Optional, Sequence

import pandas as pd
import vectorbt as vbt

from domain.vectorbt import VectorBTPortfolioSimulation


class VectorBTClientError(Exception):
    """Raised when VectorBT input validation or simulation fails."""

    def __init__(
        self,
        message: str,
        code: str = "VECTORBT_CLIENT_ERROR",
    ) -> None:
        """Initialize a VectorBT client exception.

        Args:
            message: Human-readable failure details.
            code: Stable application error code identifying the failure.

        Returns:
            None.
        """
        super().__init__(message)
        self.code = code


class VectorBTClient:
    """Run VectorBT portfolio simulations with caller-prepared inputs."""

    def simulate_portfolio(
        self,
        *,
        prices: pd.DataFrame,
        target_exposure: pd.DataFrame,
        frequency: str,
        initial_cash: float = 10_000.0,
        fees: float = 0.0,
        slippage: float = 0.0,
        excluded_direction_symbols: Optional[Sequence[str]] = None,
    ) -> VectorBTPortfolioSimulation:
        """Simulate a portfolio from prices and target percentage exposures.

        ``target_exposure`` uses VectorBT target-percent semantics. Non-null
        rows trigger portfolio rebalancing, while null rows leave the current
        holdings unchanged. Positive values represent long exposure and
        negative values represent short exposure.

        Args:
            prices: Complete numeric price data indexed by unique, sorted
                timestamps with one column per symbol. Values must be finite,
                non-null, and greater than zero.
            target_exposure: DataFrame with the same index and columns as
                prices. Rebalance rows contain decimal target exposures and
                non-rebalance rows contain null values.
            frequency: VectorBT-compatible pandas frequency such as ``1d``,
                ``1h``, or ``5min``.
            initial_cash: Starting cash value for the simulation.
            fees: Proportional transaction fee applied by VectorBT.
            slippage: Proportional execution slippage applied by VectorBT.
            excluded_direction_symbols: Synthetic symbols to exclude when
                calculating leverage-adjusted direction, such as a financing
                position.

        Returns:
            VectorBTPortfolioResult: Normalized return series and metrics. All
            return values are decimal fractions rather than percentages.

        Raises:
            VectorBTClientError: If VectorBT cannot simulate the supplied
                inputs or returns an empty result.
        """
        if initial_cash <= 0:
            raise VectorBTClientError(
                message="VectorBT initial_cash must be greater than zero",
                code="VECTORBT_INVALID_INITIAL_CASH",
            )
        if fees < 0:
            raise VectorBTClientError(
                message="VectorBT fees cannot be negative",
                code="VECTORBT_INVALID_FEES",
            )
        if slippage < 0:
            raise VectorBTClientError(
                message="VectorBT slippage cannot be negative",
                code="VECTORBT_INVALID_SLIPPAGE",
            )

        try:
            portfolio = vbt.Portfolio.from_orders(
                close=prices,
                size=target_exposure,
                size_type="targetpercent",
                direction="both",
                init_cash=float(initial_cash),
                cash_sharing=True,
                group_by=True,
                call_seq="auto",
                fees=float(fees),
                slippage=float(slippage),
                freq=frequency.lower(),
            )

            cumulative_returns = portfolio.cumulative_returns()
            if not isinstance(cumulative_returns, pd.Series):
                cumulative_returns = pd.Series(
                    cumulative_returns,
                    index=prices.index,
                )
            if cumulative_returns.empty:
                raise VectorBTClientError(
                    message="VectorBT returned an empty cumulative return series",
                    code="VECTORBT_EMPTY_RESULT",
                )

            cagr = portfolio.annualized_return()
            annualized_volatility = portfolio.annualized_volatility()

            asset_value = portfolio.asset_value(group_by=False)
            if isinstance(asset_value, pd.Series):
                asset_value = asset_value.to_frame()
            excluded_symbols = set(excluded_direction_symbols or ())
            included_columns = [
                column
                for column in asset_value.columns
                if str(column) not in excluded_symbols
            ]
            final_portfolio_value = portfolio.value().iloc[-1]
            leverage_adjusted_direction = (
                None
                if pd.isna(final_portfolio_value) or final_portfolio_value == 0
                else float(asset_value[included_columns].iloc[-1].sum())
                / float(final_portfolio_value)
            )

            return VectorBTPortfolioSimulation(
                timestamps=[
                    timestamp.to_pydatetime()
                    if isinstance(timestamp, pd.Timestamp)
                    else timestamp
                    for timestamp in cumulative_returns.index
                ],
                cumulative_returns=[
                    float(value) for value in cumulative_returns.to_numpy()
                ],
                final_cumulative_return=float(cumulative_returns.iloc[-1]),
                cagr=None if pd.isna(cagr) else float(cagr),
                annualized_volatility=(
                    None
                    if pd.isna(annualized_volatility)
                    else float(annualized_volatility)
                ),
                leverage_adjusted_direction=leverage_adjusted_direction,
            )
        except VectorBTClientError:
            raise
        except Exception as error:
            raise VectorBTClientError(
                message=f"Failed to simulate portfolio with VectorBT: {error}",
                code="VECTORBT_SIMULATION_FAILED",
            ) from error

