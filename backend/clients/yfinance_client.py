# backend/clients/market_data.py

# Python imports
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

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
    """
    Thin wrapper around yfinance that returns normalized OHLCV frames.

    Normalized output:
      - index: datetime (pd.DatetimeIndex)
      - columns: ["open", "high", "low", "close", "volume"]
    """

    progress: bool = False

    def fetch_history(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Fetch OHLCV between start_date and end_date (YYYY-MM-DD).

        IMPORTANT: yfinance treats `end` as exclusive, so we add +1 day
        to make end_date inclusive.

        Args:
            ticker: Asset ticker symbol (for example, "AAPL").
            start_date: Inclusive start date in YYYY-MM-DD format.
            end_date: Inclusive end date in YYYY-MM-DD format.
            interval: yfinance interval string. Defaults to "1d".

        Returns:
            pd.DataFrame: Normalized OHLCV frame with datetime index and
            columns ["open", "high", "low", "close", "volume"].
            Returns an empty DataFrame for invalid dates, invalid ranges,
            or unavailable data.
        """

        start_ts = pd.to_datetime(start_date).normalize()
        end_ts = pd.to_datetime(end_date).normalize()

        # If caller gives the same day (or bad ordering), make it at least 1-day window
        if end_ts < start_ts:
            raise YFinanceClientError(
                message=(
                    f"Invalid date range for ticker '{ticker}': "
                    f"end_date '{end_date}' is before start_date '{start_date}'"
                ),
                code="YFINANCE_INVALID_DATE_RANGE",
            )

        end_exclusive = end_ts + pd.Timedelta(days=1)

        try:
            df = yf.download(
                str(ticker).upper(),
                start=start_ts.date().isoformat(),
                end=end_exclusive.date().isoformat(),
                interval=interval,
                progress=self.progress,
            )
        except Exception as e:
            raise YFinanceClientError(
                message=f"Failed to download yfinance history for ticker '{ticker}': {e}",
                code="YFINANCE_FETCH_HISTORY_FAILED",
            )
        return self._normalize_ohlcv(df)

    # -------------------------
    # Internal normalization
    # -------------------------

    def _normalize_ohlcv(self, df: Optional[pd.DataFrame]) -> pd.DataFrame:
        """
        Convert yfinance output into a stable format used throughout the backend.

        - Fix MultiIndex columns (e.g., ('Close','AAPL'))
        - Drop duplicated columns defensively (prevents out['close'] returning a DataFrame)
        - Handle both 'Date' and 'Datetime' index/column names
        - Standardize column names to open/high/low/close/volume
        - Ensure datetime index

        Args:
            df: Raw DataFrame returned by yfinance download APIs.

        Returns:
            pd.DataFrame: Normalized OHLCV DataFrame with datetime index and
            columns ["open", "high", "low", "close", "volume"].
            Returns an empty DataFrame if input is invalid, empty, or missing
            required fields.
        """
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return pd.DataFrame()

        df = df.copy()

        # Fix MultiIndex columns like ('Close', 'AAPL')
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Drop duplicated column names so df["Close"] is a Series, not a DataFrame
        if df.columns.has_duplicates:
            df = df.loc[:, ~df.columns.duplicated(keep="first")]

        # yfinance returns index named Date/Datetime
        df = df.reset_index()

        # Identify timestamp column after reset_index
        ts_col = None
        if "Datetime" in df.columns:
            ts_col = "Datetime"
        elif "Date" in df.columns:
            ts_col = "Date"
        elif "index" in df.columns:
            ts_col = "index"

        if ts_col is None:
            return pd.DataFrame()

        df = df.rename(
            columns={
                ts_col: "dt",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Adj Close": "adj_close",
                "Volume": "volume",
            }
        )

        df["dt"] = pd.to_datetime(df["dt"], errors="coerce")
        df = df.dropna(subset=["dt"]).set_index("dt").sort_index()

        wanted = ["open", "high", "low", "close", "volume"]
        if any(c not in df.columns for c in wanted):
            return pd.DataFrame()

        out = df[wanted].copy()

        # Ensure each column is 1-D Series (guard against any weird shapes)
        for c in wanted:
            col = out[c]
            if isinstance(col, pd.DataFrame):  # extremely defensive
                col = col.iloc[:, 0]
            out[c] = pd.to_numeric(col, errors="coerce")

        out = out.dropna(subset=["close"])
        return out
