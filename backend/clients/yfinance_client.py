# backend/clients/market_data.py

# Python imports
from __future__ import annotations
from typing import List
from datetime import datetime, timezone

# Pandas imports
import pandas as pd

# YFinance import
import yfinance as yf


class YFinanceClientError(Exception):
    """Raised when yfinance client operations fail."""

    def __init__(self, message: str, code: str = "YFINANCE_CLIENT_ERROR") -> None:
        """
        Initialize a yfinance client exception.

        Args:
            message: Human-readable error details.
            code: Stable error code identifying the failed yfinance operation.

        Returns:
            None.
        """
        super().__init__(message)
        self.code = code

class YFinanceClient:
    """Thin wrapper around yfinance for wide close-price DataFrames."""

    progress: bool = False

    def get_stock_prices_over_time(
        self,
        symbols: List[str],
        start_datetime: datetime,
        end_datetime: datetime,
        timeframe: str,
    ) -> pd.DataFrame:
        """Fetch stock close prices over time as a wide pandas DataFrame.

        Args:
            symbols: Ticker symbols to fetch prices for.
            start_datetime: Inclusive timezone-aware start datetime. The value
                is converted to UTC before requesting prices.
            end_datetime: Exclusive timezone-aware end datetime. The value is
                converted to UTC before requesting prices.
            timeframe: Price interval. Supported values are 1Min, 5Min, 1H,
                and 1D, including their common lowercase aliases.

        Returns:
            pd.DataFrame: DataFrame indexed by UTC timestamps named
            ``timestamp``, with one column per requested symbol. Cell values
            are close prices.

        Raises:
            YFinanceClientError: If either datetime is timezone-naive, the
                date range or timeframe is invalid, or yfinance fails while
                fetching or parsing prices.
        """
        try:

            price_series_by_symbol = {}
            for symbol in symbols:
                download_kwargs = {
                    "interval": timeframe.lower(),
                    "progress": self.progress,
                }
                if start_datetime <= datetime(1970, 1, 1, tzinfo=timezone.utc):
                    download_kwargs["period"] = "max"
                else:
                    download_kwargs["start"] = start_datetime
                    download_kwargs["end"] = end_datetime

                raw_prices = yf.download(
                    str(symbol).upper(),
                    **download_kwargs,
                )

                if raw_prices is None or raw_prices.empty:
                    price_series_by_symbol[symbol] = pd.Series(dtype="float64")
                    continue

                if isinstance(raw_prices.columns, pd.MultiIndex):
                    close_data = raw_prices.xs("Close", axis=1, level=0)
                    close_prices = (
                        close_data.iloc[:, 0]
                        if isinstance(close_data, pd.DataFrame)
                        else close_data
                    )
                else:
                    close_prices = raw_prices["Close"]

                close_prices = pd.to_numeric(
                    close_prices,
                    errors="coerce",
                ).dropna()
                close_prices.index = pd.to_datetime(
                    close_prices.index,
                    utc=True,
                )
                close_prices = close_prices.loc[
                    (close_prices.index >= start_datetime)
                    & (close_prices.index < end_datetime)
                ]
                price_series_by_symbol[symbol] = close_prices.astype("float64")

            prices_df = pd.DataFrame(
                price_series_by_symbol,
                columns=symbols,
                dtype="float64",
            ).sort_index()
            prices_df.index = pd.to_datetime(prices_df.index, utc=True)
            prices_df.index.name = "timestamp"
            return prices_df
        except YFinanceClientError:
            raise
        except Exception as error:
            raise YFinanceClientError(
                message=(
                    "Failed to fetch stock prices over time for symbols "
                    f"{symbols}: {error}"
                ),
                code="YFINANCE_GET_STOCK_PRICES_OVER_TIME_FAILED",
            ) from error
