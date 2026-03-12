"""
Databento data adapter — pulls historical futures bars for backtesting.
API key must be set via DATABENTO_API_KEY environment variable.
"""
import os
import logging
from datetime import date
from typing import Optional

import databento as db

from src.strategy.core import Bar

logger = logging.getLogger(__name__)

# CME Globex dataset for futures
DATASET = "GLBX.MDP3"


def get_client(api_key: Optional[str] = None) -> db.Historical:
    """Create a Databento Historical client."""
    key = api_key or os.environ.get("DATABENTO_API_KEY", "")
    if not key:
        raise ValueError("DATABENTO_API_KEY not set. Pass it or set env var.")
    return db.Historical(key)


def fetch_futures_bars(
    symbol: str,
    start: str,
    end: str,
    stype: str = "continuous",
    schema: str = "ohlcv-1m",
    api_key: Optional[str] = None,
) -> list[Bar]:
    """
    Fetch historical OHLCV bars from Databento.

    Args:
        symbol: Futures symbol, e.g. "MES.v.0" (front month continuous),
                "MNQ.v.0", "MCL.v.0", etc.
        start: Start date, e.g. "2025-01-01"
        end: End date, e.g. "2025-12-31"
        stype: Symbol type — "continuous" for continuous front-month,
               "raw_symbol" for specific contracts like "MESH6"
        schema: Data schema — "ohlcv-1m" for 1-minute bars,
                "ohlcv-1h" for 1-hour bars, "ohlcv-1d" for daily
        api_key: Databento API key (or uses DATABENTO_API_KEY env var)

    Returns:
        List of Bar objects sorted by timestamp.
    """
    client = get_client(api_key)

    logger.info(
        "Fetching %s data: symbol=%s, range=%s to %s",
        schema, symbol, start, end,
    )

    data = client.timeseries.get_range(
        dataset=DATASET,
        symbols=[symbol],
        schema=schema,
        stype_in=stype,
        start=start,
        end=end,
    )

    # Convert to DataFrame for easy processing
    df = data.to_df()

    if df.empty:
        logger.warning("No data returned for %s (%s to %s)", symbol, start, end)
        return []

    bars = []
    for idx, row in df.iterrows():
        # Databento OHLCV prices are in fixed-point (multiply by 1e-9 for dollars)
        scale = 1e-9
        ts = idx.timestamp() if hasattr(idx, 'timestamp') else float(idx)

        bars.append(Bar(
            timestamp=ts,
            open=row["open"] * scale,
            high=row["high"] * scale,
            low=row["low"] * scale,
            close=row["close"] * scale,
            volume=float(row["volume"]),
        ))

    logger.info("Fetched %d bars for %s", len(bars), symbol)
    return bars


def aggregate_bars(bars: list[Bar], factor: int = 2) -> list[Bar]:
    """
    Aggregate bars by a given factor (e.g., 1-min -> 2-min with factor=2).
    """
    result = []
    for i in range(0, len(bars) - factor + 1, factor):
        group = bars[i:i + factor]
        result.append(Bar(
            timestamp=group[0].timestamp,
            open=group[0].open,
            high=max(b.high for b in group),
            low=min(b.low for b in group),
            close=group[-1].close,
            volume=sum(b.volume for b in group),
        ))
    return result


# ─────────────────────────────────────────────
# Convenience functions for common contracts
# ─────────────────────────────────────────────

# Continuous front-month symbol mapping for Databento
CONTINUOUS_SYMBOLS = {
    "MES": "MES.v.0",   # Micro E-mini S&P 500
    "MNQ": "MNQ.v.0",   # Micro E-mini Nasdaq-100
    "MYM": "MYM.v.0",   # Micro E-mini Dow
    "MCL": "MCL.v.0",   # Micro WTI Crude Oil
    "MGC": "MGC.v.0",   # Micro Gold
    "SIL": "SIL.v.0",   # Micro Silver
}


def fetch_contract_bars(
    root: str,
    start: str,
    end: str,
    timeframe: str = "2min",
    api_key: Optional[str] = None,
) -> list[Bar]:
    """
    High-level function: fetch bars for a contract root (e.g., "MES").
    Handles continuous symbol mapping and aggregation.

    Args:
        root: Contract root like "MES", "MNQ", etc.
        start: Start date "YYYY-MM-DD"
        end: End date "YYYY-MM-DD"
        timeframe: "1min", "2min", "5min", "1hr", "daily"
        api_key: Databento API key

    Returns:
        List of Bar objects at the requested timeframe.
    """
    symbol = CONTINUOUS_SYMBOLS.get(root)
    if symbol is None:
        raise ValueError(f"Unknown contract root: {root}. Known: {list(CONTINUOUS_SYMBOLS.keys())}")

    # Map timeframe to schema and aggregation factor
    schema_map = {
        "1min": ("ohlcv-1m", 1),
        "2min": ("ohlcv-1m", 2),   # Fetch 1-min, aggregate to 2-min
        "5min": ("ohlcv-1m", 5),   # Fetch 1-min, aggregate to 5-min
        "1hr":  ("ohlcv-1h", 1),
        "daily": ("ohlcv-1d", 1),
    }

    if timeframe not in schema_map:
        raise ValueError(f"Unknown timeframe: {timeframe}. Options: {list(schema_map.keys())}")

    schema, agg_factor = schema_map[timeframe]

    bars = fetch_futures_bars(
        symbol=symbol,
        start=start,
        end=end,
        stype="continuous",
        schema=schema,
        api_key=api_key,
    )

    if agg_factor > 1:
        original_count = len(bars)
        bars = aggregate_bars(bars, factor=agg_factor)
        logger.info(
            "Aggregated %d x %d-min bars -> %d x %s bars",
            original_count, 1, len(bars), timeframe,
        )

    return bars
