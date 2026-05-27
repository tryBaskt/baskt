# backend/clients/alpaca_client.py

# Python imports
from __future__ import annotations
from typing import List, Dict
from math import ceil
from time import sleep, time

# Alpaca imports
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from alpaca.trading.models import Position, Asset
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.models import Order

# Pandas imports
import pandas as pd

# Baskt imports
from domain.baskt import BasktPosition


class AlpacaClientError(Exception):
    """Raised when Alpaca client operations fail."""

    def __init__(self, message: str, code: str = "ALPACA_CLIENT_ERROR"):
        super().__init__(message)
        self.code = code

class AlpacaClient:
    """
    Alpaca client wrapper
    """

    def __init__(self, *, alpaca_api_key, alpaca_api_secret):
        """
        Initialize trading and market-data clients for Alpaca.

        Args:
            alpaca_api_key: Alpaca API key.
            alpaca_api_secret: Alpaca API secret.

        Returns:
            None.
        """
        self.client = TradingClient(api_key=alpaca_api_key, secret_key=alpaca_api_secret)
        self.data_client = StockHistoricalDataClient(api_key=alpaca_api_key, secret_key=alpaca_api_secret)

    def get_tradeable_fractionable_US_assets(self) -> List[Asset]:
        """
        Fetch all Alpaca assets and filter to tradable, fractionable US equities.

        Args:
            None.

        Returns:
            List[Asset]: Assets where tradable=True, fractionable=True,
            and asset_class is US_EQUITY.
        """
        try:
            assets = self.client.get_all_assets()
        except Exception as e:
            raise AlpacaClientError(
                message=f"Failed to fetch tradable, fractionable US Alpaca assets: {e}",
                code="ALPACA_GET_ASSETS_FAILED",
            )

        tradeable = []
        for asset in assets:
            asset_class = getattr(asset.asset_class, "name", asset.asset_class)
            if asset.tradable and asset_class in {"US_EQUITY", "us_equity"} and asset.fractionable:
                tradeable.append(asset)

        return tradeable


    def get_order_by_id(self, order_id: str) -> Order:
        """
        Retrieve a single order from Alpaca by its unique order ID.

        Args:
            order_id: Alpaca order UUID string to fetch.

        Returns:
            Order: Alpaca Order model for the requested order ID.
        """
        try:
            return self.client.get_order_by_id(order_id=order_id)
        except Exception as e:
            raise AlpacaClientError(
                message=f"Failed to fetch Alpaca order '{order_id}': {e}",
                code="ALPACA_GET_ORDER_FAILED",
            )


    def get_baskt_positions_dict(self) -> Dict[str, BasktPosition]:
        """
        Build a dictionary of current Baskt positions keyed by symbol.

        Args:
            None.

        Returns:
            Dict[str, BasktPosition]: Mapping of symbol to BasktPosition.
        """

        baskt_positions:  List[BasktPosition]= self.get_baskt_positions()
        if not baskt_positions:
            return {}
        
        baskt_positions_dict = {
            baskt_position.symbol: baskt_position
            for baskt_position in baskt_positions
        }

        return baskt_positions_dict
    
    def get_baskt_positions(self) -> List[BasktPosition]:
        """
        Fetch all open Alpaca positions and convert them into BasktPosition models.

        Args:
            None.

        Returns:
            List[BasktPosition]: One BasktPosition per open Alpaca position,
            with symbol, absolute filled quantity, normalized direction
            (1 for long, -1 for short), and average filled price.

        Raises:
            ValueError: If Alpaca returns a position side other than LONG or SHORT.
        """
        try:
            all_positions:  List[Position]= self.client.get_all_positions()
        except Exception as e:
            raise AlpacaClientError(
                message=f"Failed to fetch baskt positions: {e}",
                code="ALPACA_GET_POSITIONS_FAILED",
            )

        if not all_positions:
            return []
            
        baskt_positions: List[BasktPosition] = []
        for position in all_positions:
            avg_price = float(position.avg_entry_price)
            filled_quantity = abs(float(position.qty))

            direction = 0
            if position.side.name == "LONG":
                direction = 1
            elif position.side.name == "SHORT":
                direction = -1
            else:
                raise ValueError(f"Unexpected position side {position.symbol}: {position.side}")

            baskt_positions.append(
                BasktPosition(
                    symbol=position.symbol,
                    filled_quantity=filled_quantity,
                    direction=direction,
                    filled_avg_price=avg_price,
                )
            )
        return baskt_positions
    

    def execute_close_position(self, symbol: str) -> Order:
        """
        Submit an order request to close an open position for a symbol.

        Args:
            symbol: Ticker symbol or asset identifier to close.

        Returns:
            Order: Alpaca order response for the close-position request.
        """

        try:
            return self.client.close_position(symbol_or_asset_id=symbol)
        except Exception as e:
            raise AlpacaClientError(
                message=f"Failed to close Alpaca position '{symbol}': {e}",
                code="ALPACA_CLOSE_POSITION_FAILED",
            )


    def execute_quantity_buy(self,symbol: str, quantity: float) -> Order:
        """
        Submit a market buy order for a specific quantity.

        Args:
            symbol: Ticker symbol to buy.
            quantity: Number of shares to buy.

        Returns:
            Order: Alpaca order response for the buy request.
        """

        order_req = MarketOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        try:
            return self.client.submit_order(order_data=order_req)
        except Exception as e:
            raise AlpacaClientError(
                message=f"Failed to submit buy order for '{symbol}': {e}",
                code="ALPACA_BUY_ORDER_FAILED",
            )


    def execute_quantity_fractional_sell(self,symbol: str, quantity) -> List[Order | None]:
        """
        Reduce a position using a two-step order flow for fractional quantities.

        The method first sells ceil(quantity) shares, then optionally buys back
        the overage to land on the exact fractional reduction.

        Args:
            symbol: Ticker symbol to sell.
            quantity: Quantity to reduce from the position; may be fractional.

        Returns:
            tuple[Order, Optional[Order]]: The initial sell order and an
            optional buy-back order (None when no buy-back is needed).
        """

        order_req = MarketOrderRequest(
            symbol=symbol,
            qty=ceil(quantity),
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        try:
            order1 = self.client.submit_order(order_data=order_req)
        except Exception as e:
            raise AlpacaClientError(
                message=f"Failed to submit initial fractional sell for '{symbol}': {e}",
                code="ALPACA_FRACTIONAL_SELL_FAILED",
            )

        if ceil(quantity)-quantity <= 0:
            return [order1,None]
        
        order1_id = order1.id
        while self.get_order_by_id(order1_id).status.name != "FILLED":
            sleep(0.25)

        order_req = MarketOrderRequest(
            symbol=symbol,
            qty=ceil(quantity)-quantity,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )

        try:
            order2 = self.client.submit_order(order_data=order_req)
        except Exception as e:
            raise AlpacaClientError(
                message=f"Failed to submit fractional buy-back for '{symbol}': {e}",
                code="ALPACA_FRACTIONAL_BUYBACK_FAILED",
            )
        return [order1,order2]


    def execute_quantity_sell(self,symbol: str, quantity: float) -> Order:
        """
        Submit a market sell order for a specific quantity.

        Args:
            symbol: Ticker symbol to sell.
            quantity: Number of shares to sell.

        Returns:
            Order: Alpaca order response for the sell request.
        """

        order_req = MarketOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        try:
            return self.client.submit_order(order_data=order_req)
        except Exception as e:
            raise AlpacaClientError(
                message=f"Failed to submit sell order for '{symbol}': {e}",
                code="ALPACA_SELL_ORDER_FAILED",
            )


    def get_latest_price(self, symbols: List[str]) -> Dict[str, float]:
        """
        Fetch latest trade prices for each requested symbol.

        Args:
            symbols: List of ticker symbols.

        Returns:
            Dict[str, Optional[float]]: Mapping of symbol to latest price.
        """
        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=symbols)
            quotes = self.data_client.get_stock_latest_trade(request)
        except Exception as e:
            raise AlpacaClientError(
                message=f"Failed to fetch latest prices for symbols {symbols}: {e}",
                code="ALPACA_GET_LATEST_PRICE_FAILED",
            )
        result = {}
        for symbol in symbols:
            if symbol not in quotes:
                raise AlpacaClientError(
                    message=f"Latest price missing for symbol '{symbol}'",
                    code="ALPACA_MISSING_LATEST_PRICE",
                )
            result[symbol] = quotes[symbol].price 

        return result
    
    # def get_symbols_price_history(self, symbols: List[str], start_datetime_utc: datetime, end_datetime_utc: datetime, time_frame_amount: int, time_frame_unit: Any) -> pd.DataFrame:
    #     """
    #     Retrieve historical OHLCV bars for symbols within a UTC time range.

    #     Args:
    #         symbols: List of ticker symbols.
    #         start_datetime_utc: Start of requested window in UTC.
    #         end_datetime_utc: End of requested window in UTC.
    #         time_frame_amount: Timeframe amount (for example, 1, 5, 15).
    #         time_frame_unit: Timeframe unit compatible with Alpaca TimeFrame.

    #     Returns:
    #         pd.DataFrame: Bar data sorted by timestamp. Returns an empty
    #         DataFrame when no bars are available.
    #     """
    #     req = StockBarsRequest(
    #         symbol_or_symbols=symbols,
    #         timeframe=TimeFrame(amount=time_frame_amount, unit = time_frame_unit),   # <-- interval
    #         start=start_datetime_utc,
    #         end=end_datetime_utc,
    #         feed=DataFeed.IEX
    #     )

    #     bars = self.data_client.get_stock_bars(req)
    #     df: pd.DataFrame = bars.df
    #     if df is not None and not df.empty:
    #         df = df.reset_index()
    #         df = df.sort_values(by='timestamp')
    #     return df

    def close_all_positions(self, cancel_open_orders: bool = True, wait: bool = True, timeout_sec: int = 20, poll_interval_sec: float = 2.0) -> bool:
        """
        Close all open positions in the Alpaca account.

        Args:
            cancel_open_orders: If True, cancels existing open orders before closing positions.
            wait: If True, polls until positions are cleared or timeout is reached.
            timeout_sec: Max seconds to wait for all positions to be closed.
            poll_interval_sec: Interval between position polls.

        Returns:
            True if positions are cleared (or wait=False), False if timeout reached while waiting.
        """
        # Submit close-all request
        try:
            self.client.close_all_positions(cancel_orders=cancel_open_orders)
        except Exception as e:
            raise AlpacaClientError(
                message=f"Failed to close all positions: {e}",
                code="ALPACA_CLOSE_ALL_POSITIONS_FAILED",
            )

        if not wait:
            return True

        deadline = time() + timeout_sec
        while time() < deadline:
            try:
                positions = self.client.get_all_positions()
            except Exception as e:
                raise AlpacaClientError(
                    message=f"Failed while polling remaining positions: {e}",
                    code="ALPACA_POLL_POSITIONS_FAILED",
                )
            if not positions:
                return True
            sleep(poll_interval_sec)
        return False
    

    # def get_user_allocation_history_graphs(self, period: str, timeframe: str):
    #     """
    #     Fetch account portfolio history formatted for graphing.

    #     Args:
    #         period: Portfolio history period (for example, 1M, 3M, 1Y).
    #         timeframe: Candle interval used by Alpaca history endpoint.

    #     Returns:
    #         Dict[str, List[Any]]: Dictionary with UTC timestamps (`ts_utc`)
    #         and corresponding equity values (`equity`).
    #     """
    #     req = GetPortfolioHistoryRequest(period=period, timeframe=timeframe)
    #     ph = self.client.get_portfolio_history(req)
    #     timestamps = ph.timestamp
    #     ts_utc = [datetime.fromtimestamp(t, tz=timezone.utc) for t in timestamps]
    #     equity = ph.equity
    #     return {"ts_utc": ts_utc, "equity": equity}




    

