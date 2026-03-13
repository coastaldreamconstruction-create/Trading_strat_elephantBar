"""
Alpaca broker interface — account info, historical data, order execution,
and real-time bar streaming.

NOTE: The original bug "'tuple' object has no attribute 'lower'" was caused
by passing a *tuple* (e.g. ("AAPL",)) instead of a plain string "AAPL" to
the Alpaca SDK's historical-bars request.  The SDK internally calls
symbol.lower(), which fails on tuples.  This module is careful to always
pass individual symbol strings.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Callable

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.live import StockDataStream
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from config.settings import (
    ALPACA_API_KEY,
    ALPACA_DATA_FEED,
    ALPACA_SECRET_KEY,
    PAPER_MODE,
)

log = logging.getLogger("broker")


class Broker:
    """Thin wrapper around Alpaca's trading + data clients."""

    def __init__(self) -> None:
        self._trading = TradingClient(
            ALPACA_API_KEY,
            ALPACA_SECRET_KEY,
            paper=PAPER_MODE,
        )
        self._data = StockHistoricalDataClient(
            ALPACA_API_KEY,
            ALPACA_SECRET_KEY,
        )
        self._stream: StockDataStream | None = None

    # ── Account ─────────────────────────────────────────────────────────

    def get_account(self):
        return self._trading.get_account()

    # ── Historical bars ─────────────────────────────────────────────────

    def get_daily_bars(
        self,
        symbol: str,
        days: int = 400,
    ) -> pd.DataFrame:
        """Fetch *daily* bars for a single symbol.

        The symbol MUST be a plain string — never a tuple or list.
        """
        # Defensive: ensure symbol is a string (fixes the original bug)
        if not isinstance(symbol, str):
            raise TypeError(
                f"symbol must be a str, got {type(symbol).__name__}: {symbol!r}"
            )

        end = datetime.now()
        start = end - timedelta(days=days)

        request = StockBarsRequest(
            symbol_or_symbols=symbol,   # single string, NOT a tuple
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
        )
        barset = self._data.get_stock_bars(request)
        df = barset.df

        if df.empty:
            return df

        # If multi-index (symbol, timestamp), drop the symbol level
        if isinstance(df.index, pd.MultiIndex):
            df = df.droplevel("symbol")

        return df

    def get_minute_bars(
        self,
        symbol: str,
        days: int = 10,
    ) -> pd.DataFrame:
        """Fetch 1-minute bars for a single symbol."""
        if not isinstance(symbol, str):
            raise TypeError(
                f"symbol must be a str, got {type(symbol).__name__}: {symbol!r}"
            )

        end = datetime.now()
        start = end - timedelta(days=days)

        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            start=start,
            end=end,
        )
        barset = self._data.get_stock_bars(request)
        df = barset.df

        if df.empty:
            return df

        if isinstance(df.index, pd.MultiIndex):
            df = df.droplevel("symbol")

        return df

    # ── Streaming ───────────────────────────────────────────────────────

    async def stream_bars(
        self,
        symbols: list[str],
        on_bar: Callable,
    ) -> None:
        """Subscribe to real-time 1-minute bars via websocket."""
        self._stream = StockDataStream(
            ALPACA_API_KEY,
            ALPACA_SECRET_KEY,
            feed=ALPACA_DATA_FEED,
        )
        log.info("Streaming bars for: %s", ", ".join(symbols))

        self._stream.subscribe_bars(on_bar, *symbols)
        await self._stream._run_forever()

    async def stop_stream(self) -> None:
        if self._stream is not None:
            await self._stream.stop()

    # ── Orders ──────────────────────────────────────────────────────────

    def submit_market_order(
        self,
        symbol: str,
        qty: float,
        side: str,
    ):
        """Submit a market order. side = 'buy' | 'sell'."""
        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=order_side,
            time_in_force=TimeInForce.DAY,
        )
        order = self._trading.submit_order(req)
        log.info(
            "Order submitted: %s %s x%.2f @ market → %s",
            side.upper(), symbol, qty, order.id,
        )
        return order

    def get_positions(self):
        return self._trading.get_all_positions()

    def close_position(self, symbol: str):
        log.info("Closing position: %s", symbol)
        return self._trading.close_position(symbol)

    def close_all_positions(self):
        log.info("Closing all positions")
        return self._trading.close_all_positions()
