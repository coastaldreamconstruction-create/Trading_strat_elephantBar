"""
Pre-market screener — checks market condition (SPY) and filters the
watchlist for tradeable candidates based on price, volume, and volatility.

BUGFIX: The original code triggered "'tuple' object has no attribute 'lower'"
because the symbol was inadvertently wrapped in a tuple before being passed
to the Alpaca bars API.  This version always passes a plain string.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from config.settings import (
    MARKET_MA_LONG,
    MARKET_MA_SHORT,
    MARKET_TICKER,
    SCREENER_MAX_PRICE,
    SCREENER_MIN_ATR_PCT,
    SCREENER_MIN_AVG_VOLUME,
    SCREENER_MIN_PRICE,
)
from src.data.broker import Broker

log = logging.getLogger("screener")


def _compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)

    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)

    return tr.rolling(period).mean()


# ── Market condition ────────────────────────────────────────────────────

def check_market_condition(broker: Broker) -> dict:
    """Evaluate broad-market health using SPY moving averages.

    Returns a dict with state, ma values, and a boolean 'tradeable' flag.
    """
    df = broker.get_daily_bars(MARKET_TICKER, days=300)

    if df.empty or len(df) < MARKET_MA_LONG:
        log.warning("Not enough SPY data for market condition check.")
        return {"state": "UNKNOWN", "tradeable": False}

    ma_short = df["close"].rolling(MARKET_MA_SHORT).mean().iloc[-1]
    ma_long = df["close"].rolling(MARKET_MA_LONG).mean().iloc[-1]

    if ma_short > ma_long:
        state = "NORMAL"
    elif ma_short < ma_long * 0.97:
        state = "BEARISH"
    else:
        state = "CAUTION"

    tradeable = state in ("NORMAL", "CAUTION")

    print(
        "\n" + "=" * 60 + "\n"
        f"MARKET CONDITION ({MARKET_TICKER})\n"
        f"  State:      {state}\n"
        f"  MA{MARKET_MA_SHORT}:       {ma_short:,.2f}\n"
        f"  MA{MARKET_MA_LONG}:      {ma_long:,.2f}\n"
        f"  Tradeable:  {'✅ YES' if tradeable else '❌ NO'}\n"
        + "=" * 60
    )

    return {
        "state": state,
        "ma_short": ma_short,
        "ma_long": ma_long,
        "tradeable": tradeable,
    }


# ── Stock screener ──────────────────────────────────────────────────────

def screen_stocks(
    broker: Broker,
    symbols: list[str],
) -> list[str]:
    """Run the pre-market screener and return symbols that pass all filters.

    Each symbol is a plain *string* — never a tuple.
    """
    log.info("Screening %d stocks...", len(symbols))
    candidates: list[str] = []

    for symbol in symbols:
        # Defensive: ensure we pass a string, not a tuple
        symbol = str(symbol).strip()

        try:
            df = broker.get_daily_bars(symbol, days=60)
        except Exception as exc:
            log.warning("Could not fetch daily data for %s: %s", symbol, exc)
            continue

        if df.empty or len(df) < 20:
            log.debug("%s: insufficient data (%d bars)", symbol, len(df))
            continue

        last_close = df["close"].iloc[-1]
        avg_volume = df["volume"].tail(20).mean()
        atr = _compute_atr(df).iloc[-1]
        atr_pct = (atr / last_close) * 100 if last_close else 0

        # Price filter
        if not (SCREENER_MIN_PRICE <= last_close <= SCREENER_MAX_PRICE):
            log.debug("%s: price $%.2f outside range", symbol, last_close)
            continue

        # Volume filter
        if avg_volume < SCREENER_MIN_AVG_VOLUME:
            log.debug("%s: avg volume %.0f below threshold", symbol, avg_volume)
            continue

        # Volatility filter (ATR %)
        if atr_pct < SCREENER_MIN_ATR_PCT:
            log.debug("%s: ATR%% %.2f%% below threshold", symbol, atr_pct)
            continue

        log.info(
            "  ✅ %s passed — close=$%.2f  vol=%.0f  ATR%%=%.2f%%",
            symbol, last_close, avg_volume, atr_pct,
        )
        candidates.append(symbol)

    if not candidates:
        log.info("No candidates passed the screener today.")

    return candidates
