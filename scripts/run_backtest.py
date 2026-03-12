#!/usr/bin/env python3
"""
Elephant Bar Backtest Runner — Pulls real data from Databento and runs backtest.

Setup:
    pip install databento pytest

Usage:
    # Set your API key
    export DATABENTO_API_KEY="db-your-key-here"

    # Run backtest on MES (default: last 3 months, 2-min bars)
    python scripts/run_backtest.py

    # Customize contract, date range, timeframe
    python scripts/run_backtest.py --contract MNQ --start 2025-06-01 --end 2025-12-31 --timeframe 2min

    # Run all 6 contracts
    python scripts/run_backtest.py --all

    # 1-hour mode (longs only)
    python scripts/run_backtest.py --contract MES --timeframe 1hr --no-shorts

    # Save bars to CSV for reuse (avoids re-downloading)
    python scripts/run_backtest.py --contract MES --save-csv

    # Load from previously saved CSV
    python scripts/run_backtest.py --contract MES --from-csv data/MES_2min.csv
"""
import argparse
import csv
import logging
import os
import sys
from datetime import date, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.strategy.core import Bar
from src.backtest.engine import Backtester, BacktestResult
from src.data.databento_adapter import fetch_contract_bars
from src import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("backtest_runner")


def save_bars_to_csv(bars: list[Bar], filepath: str):
    """Save bars to CSV for reuse without re-downloading."""
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for bar in bars:
            writer.writerow([bar.timestamp, bar.open, bar.high, bar.low, bar.close, bar.volume])
    logger.info("Saved %d bars to %s", len(bars), filepath)


def load_bars_from_csv(filepath: str) -> list[Bar]:
    """Load bars from a previously saved CSV."""
    bars = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append(Bar(
                timestamp=float(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            ))
    logger.info("Loaded %d bars from %s", len(bars), filepath)
    return bars


def run_single_backtest(
    root: str,
    start: str,
    end: str,
    timeframe: str = "2min",
    allow_shorts: bool = True,
    save_csv: bool = False,
    from_csv: str = "",
) -> BacktestResult:
    """Run backtest for a single contract."""
    spec = config.CONTRACTS_2MIN.get(root)
    if spec is None:
        logger.error("Unknown contract root: %s", root)
        return BacktestResult(symbol=root)

    # Get bars
    if from_csv:
        bars = load_bars_from_csv(from_csv)
    else:
        api_key = os.environ.get("DATABENTO_API_KEY")
        if not api_key:
            logger.error("DATABENTO_API_KEY not set. Export it or use --from-csv.")
            sys.exit(1)

        bars = fetch_contract_bars(
            root=root,
            start=start,
            end=end,
            timeframe=timeframe,
            api_key=api_key,
        )

    if not bars:
        logger.error("No bars retrieved for %s. Check date range and API key.", root)
        return BacktestResult(symbol=root)

    # Optionally save for reuse
    if save_csv:
        csv_path = f"data/{root}_{timeframe}_{start}_to_{end}.csv"
        save_bars_to_csv(bars, csv_path)

    # Run backtest
    logger.info(
        "Running backtest: %s | %d bars | %s | shorts=%s",
        root, len(bars), timeframe, allow_shorts,
    )

    bt = Backtester(
        symbol=root,
        tick_size=spec["tick_size"],
        tick_value=spec["tick_value"],
        allow_shorts=allow_shorts,
        starting_capital=config.STARTING_CAPITAL,
        max_daily_loss=config.MAX_DAILY_LOSS,
    )
    result = bt.run(bars)
    return result


def main():
    parser = argparse.ArgumentParser(description="Elephant Bar Backtest Runner")
    parser.add_argument(
        "--contract", default="MES",
        help="Contract root: MES, MNQ, MYM, MCL, MGC, SIL (default: MES)",
    )
    parser.add_argument(
        "--start", default=None,
        help="Start date YYYY-MM-DD (default: 3 months ago)",
    )
    parser.add_argument(
        "--end", default=None,
        help="End date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--timeframe", default="2min",
        choices=["1min", "2min", "5min", "1hr", "daily"],
        help="Bar timeframe (default: 2min)",
    )
    parser.add_argument(
        "--no-shorts", action="store_true",
        help="Disable short signals",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Run backtest on all 6 contracts",
    )
    parser.add_argument(
        "--save-csv", action="store_true",
        help="Save downloaded bars to CSV for reuse",
    )
    parser.add_argument(
        "--from-csv", default="",
        help="Load bars from CSV instead of downloading",
    )

    args = parser.parse_args()

    # Default date range: last 3 months
    end_date = args.end or str(date.today())
    start_date = args.start or str(date.today() - timedelta(days=90))

    contracts = list(config.CONTRACTS_2MIN.keys()) if args.all else [args.contract]
    allow_shorts = not args.no_shorts

    print("=" * 60)
    print("Elephant Bar Breakout Strategy — Backtest")
    print(f"  Date range: {start_date} to {end_date}")
    print(f"  Timeframe:  {args.timeframe}")
    print(f"  Contracts:  {contracts}")
    print(f"  Shorts:     {'enabled' if allow_shorts else 'disabled'}")
    print("=" * 60)
    print()

    all_results = []
    for root in contracts:
        result = run_single_backtest(
            root=root,
            start=start_date,
            end=end_date,
            timeframe=args.timeframe,
            allow_shorts=allow_shorts,
            save_csv=args.save_csv,
            from_csv=args.from_csv,
        )
        all_results.append(result)
        print(result.summary())
        print()

    # Combined summary if multiple contracts
    if len(all_results) > 1:
        total_trades = sum(r.total_trades for r in all_results)
        total_pnl = sum(r.total_pnl for r in all_results)
        total_winners = sum(len(r.winners) for r in all_results)

        print("=" * 60)
        print("COMBINED RESULTS (ALL CONTRACTS)")
        print("=" * 60)
        print(f"  Total trades:   {total_trades}")
        print(f"  Total winners:  {total_winners} ({total_winners/total_trades:.1%})" if total_trades else "  Total winners:  0")
        print(f"  Total P&L:      ${total_pnl:,.2f}")
        print(f"  Final equity:   ${config.STARTING_CAPITAL + total_pnl:,.2f}")
        print("=" * 60)


if __name__ == "__main__":
    main()
