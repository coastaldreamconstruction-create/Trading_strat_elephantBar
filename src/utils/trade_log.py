"""
Simple CSV trade logger.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime

from config.settings import TRADE_LOG_PATH


def log_trade(
    symbol: str,
    side: str,
    qty: float,
    entry_price: float,
    exit_price: float | None = None,
    pnl: float | None = None,
    reason: str = "",
) -> None:
    """Append a trade record to the CSV log."""
    file_exists = os.path.isfile(TRADE_LOG_PATH)
    os.makedirs(os.path.dirname(TRADE_LOG_PATH), exist_ok=True)

    with open(TRADE_LOG_PATH, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "timestamp", "symbol", "side", "qty",
                "entry_price", "exit_price", "pnl", "reason",
            ])
        writer.writerow([
            datetime.now().isoformat(),
            symbol,
            side,
            qty,
            f"{entry_price:.2f}",
            f"{exit_price:.2f}" if exit_price is not None else "",
            f"{pnl:.2f}" if pnl is not None else "",
            reason,
        ])
