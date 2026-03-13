"""
Elephant Bar detection and signal generation.

An Elephant Bar is a candle whose body size is significantly larger than the
average body size of the preceding N candles, often accompanied by a volume
spike.  It signals strong momentum.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd

from config.settings import (
    ELEPHANT_BAR_LOOKBACK,
    ELEPHANT_BAR_MULTIPLIER,
    MA200_PERIOD,
    VOLUME_SPIKE_MULTIPLIER,
)

log = logging.getLogger("strategy")


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class Signal:
    symbol: str
    direction: Direction
    entry_price: float
    stop_loss: float
    target: float
    bar_body: float
    avg_body: float
    volume_ratio: float


def detect_elephant_bar(
    df: pd.DataFrame,
    symbol: str,
    lookback: int = ELEPHANT_BAR_LOOKBACK,
    multiplier: float = ELEPHANT_BAR_MULTIPLIER,
    volume_mult: float = VOLUME_SPIKE_MULTIPLIER,
) -> Signal | None:
    """Check if the latest bar in *df* qualifies as an elephant bar.

    Parameters
    ----------
    df : DataFrame with columns [open, high, low, close, volume].
    symbol : ticker symbol (used in the returned Signal).
    lookback : number of prior bars to average.
    multiplier : body must exceed avg_body × multiplier.
    volume_mult : volume must exceed avg_volume × volume_mult.

    Returns
    -------
    A Signal if the latest bar is an elephant bar, else None.
    """
    if len(df) < lookback + 1:
        return None

    bodies = (df["close"] - df["open"]).abs()

    current_body = bodies.iloc[-1]
    avg_body = bodies.iloc[-(lookback + 1):-1].mean()

    if avg_body == 0:
        return None

    # ── Body-size check ─────────────────────────────────────────────
    if current_body < avg_body * multiplier:
        return None

    # ── Volume check ────────────────────────────────────────────────
    avg_vol = df["volume"].iloc[-(lookback + 1):-1].mean()
    current_vol = df["volume"].iloc[-1]
    volume_ratio = current_vol / avg_vol if avg_vol else 0

    if volume_ratio < volume_mult:
        return None

    # ── Direction ───────────────────────────────────────────────────
    bar_open = df["open"].iloc[-1]
    bar_close = df["close"].iloc[-1]
    bar_high = df["high"].iloc[-1]
    bar_low = df["low"].iloc[-1]

    if bar_close > bar_open:
        direction = Direction.LONG
        stop_loss = bar_low
        target = bar_close + (bar_close - stop_loss) * 2  # 2:1 R:R
    else:
        direction = Direction.SHORT
        stop_loss = bar_high
        target = bar_close - (stop_loss - bar_close) * 2

    # ── MA200 trend filter ──────────────────────────────────────────
    if len(df) >= MA200_PERIOD:
        ma200 = df["close"].rolling(MA200_PERIOD).mean().iloc[-1]
        if direction == Direction.LONG and bar_close < ma200:
            log.debug("%s: bullish elephant bar rejected (below MA200)", symbol)
            return None
        if direction == Direction.SHORT and bar_close > ma200:
            log.debug("%s: bearish elephant bar rejected (above MA200)", symbol)
            return None

    signal = Signal(
        symbol=symbol,
        direction=direction,
        entry_price=bar_close,
        stop_loss=stop_loss,
        target=target,
        bar_body=current_body,
        avg_body=avg_body,
        volume_ratio=volume_ratio,
    )

    log.info(
        "🐘 Elephant Bar detected: %s %s @ $%.2f  "
        "body=%.2f (%.1f× avg)  vol_ratio=%.1f  SL=$%.2f  TP=$%.2f",
        symbol,
        direction.value.upper(),
        bar_close,
        current_body,
        current_body / avg_body,
        volume_ratio,
        stop_loss,
        target,
    )

    return signal
