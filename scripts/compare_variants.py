#!/usr/bin/env python3
"""
A/B Test: Compare strategy improvements independently against the baseline.

Each variant changes ONE parameter from baseline so we can isolate its effect.

Variants:
  Baseline         — Current defaults (elephant_mult=1.5, no TOD filter, no trend filter, push_exit=6)
  Higher Threshold — elephant_mult=2.0 (stricter elephant bar detection)
  RTH Only         — TOD filter: 14:30-21:00 UTC (US equity regular trading hours)
  Elephant Mult 2.5— Even stricter elephant detection
  Push Exit 8      — Let winners run longer (8 consecutive pushes instead of 6)
  Trailing Stop    — Enable trailing stop (trigger at 1x ATR, trail at 0.5x ATR)
  Longs Only       — Disable short signals entirely

Usage:
    python3 scripts/compare_variants.py
    python3 scripts/compare_variants.py --contract MES
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.run_backtest import load_bars_from_csv
from src.backtest.engine import Backtester, BacktestResult, Trade
from src import config


# ── Variant definitions ──
# Best Combo B is the baseline now (counter-mom + 2.5x + push 8)
# Phase 3: loss analysis improvements applied ON TOP of Best Combo B
_BEST_B = {
    "require_counter_momentum": True,
    "elephant_mult": 2.5,
    "push_exit_count": 8,
}

VARIANTS = {
    "Original Baseline": {
        # Original defaults for reference
    },
    "Best Combo B": {
        **_BEST_B,
    },
    "B + Skip Evening": {
        **_BEST_B,
        "tod_start_hour": 0,
        "tod_end_hour": 21,
    },
    "B + Skip Sun": {
        **_BEST_B,
        "skip_days": [6],
    },
    "B + Skip Thu/Fri/Sun": {
        **_BEST_B,
        "skip_days": [3, 4, 6],
    },
    "B + Mon-Wed Only": {
        **_BEST_B,
        "skip_days": [3, 4, 5, 6],
    },
    "B + Max 40 Ticks": {
        **_BEST_B,
        "max_stop_ticks": 40,
    },
    "B + Max 75 Ticks": {
        **_BEST_B,
        "max_stop_ticks": 75,
    },
    "B + TimeStop 150": {
        **_BEST_B,
        "time_stop_bars": 150,
    },
    "B + TimeStop 300": {
        **_BEST_B,
        "time_stop_bars": 300,
    },
    "B + Skip Eve+Sun": {
        **_BEST_B,
        "tod_start_hour": 0,
        "tod_end_hour": 21,
        "skip_days": [6],
    },
    "B+SkipEve+Sun+Max75": {
        **_BEST_B,
        "tod_start_hour": 0,
        "tod_end_hour": 21,
        "skip_days": [6],
        "max_stop_ticks": 75,
    },
    "ULTIMATE": {
        **_BEST_B,
        "tod_start_hour": 0,
        "tod_end_hour": 21,
        "skip_days": [6],
        "max_stop_ticks": 75,
        "time_stop_bars": 300,
    },
}


def find_csv(root: str) -> str:
    """Find the saved CSV for a contract root."""
    data_dir = "data"
    if not os.path.isdir(data_dir):
        return ""
    for f in sorted(os.listdir(data_dir), reverse=True):
        if f.startswith(root + "_") and f.endswith(".csv"):
            return os.path.join(data_dir, f)
    return ""


def run_variant(root: str, bars, variant_name: str, variant_kwargs: dict) -> BacktestResult:
    """Run a single backtest variant."""
    spec = config.CONTRACTS_2MIN.get(root)
    if spec is None:
        return BacktestResult(symbol=root)

    # Handle allow_shorts separately
    allow_shorts = "Longs" not in variant_name

    # Filter out non-strategy kwargs
    strat_kwargs = {k: v for k, v in variant_kwargs.items()}

    bt = Backtester(
        symbol=root,
        tick_size=spec["tick_size"],
        tick_value=spec["tick_value"],
        allow_shorts=allow_shorts,
        starting_capital=config.STARTING_CAPITAL,
        max_daily_loss=config.MAX_DAILY_LOSS,
        **strat_kwargs,
    )
    return bt.run(bars)


def print_table(results: dict, variant_names: list, title: str):
    """Print a formatted comparison table."""
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print(f"{'=' * 80}")
    print(
        f"  {'Variant':<28} {'Trades':>6} {'Win%':>6} {'AvgW':>8} "
        f"{'AvgL':>8} {'P&L':>10} {'PF':>6} {'MaxDD':>10}"
    )
    print(f"  {'─' * 28} {'─' * 6} {'─' * 6} {'─' * 8} {'─' * 8} {'─' * 10} {'─' * 6} {'─' * 10}")

    for name in variant_names:
        r = results[name]
        if r.total_trades == 0:
            print(f"  {name:<28} {'0':>6} {'N/A':>6} {'N/A':>8} {'N/A':>8} {'$0.00':>10} {'N/A':>6} {'$0.00':>10}")
            continue
        pf = f"{r.profit_factor:.2f}" if r.profit_factor != float("inf") else "inf"
        print(
            f"  {name:<28} {r.total_trades:>6} {r.win_rate:>5.1%} "
            f"${r.avg_winner:>7,.2f} ${r.avg_loser:>7,.2f} "
            f"${r.total_pnl:>9,.2f} {pf:>6} ${r.max_drawdown:>9,.2f}"
        )


def main():
    parser = argparse.ArgumentParser(description="Compare strategy variants independently")
    parser.add_argument("--contract", default=None, help="Single contract to test (default: MES)")
    args = parser.parse_args()

    # Default to all contracts we have data for
    all_contracts = ["MES", "MNQ", "MYM", "MCL", "MGC", "MSI"]
    contracts = [args.contract] if args.contract else all_contracts

    # Load bars
    contract_bars = {}
    for root in contracts:
        csv_path = find_csv(root)
        if not csv_path:
            print(f"WARNING: No CSV found for {root}. Skipping.")
            continue
        contract_bars[root] = load_bars_from_csv(csv_path)
        print(f"Loaded {len(contract_bars[root]):,} bars for {root} from {csv_path}")

    if not contract_bars:
        print("No data found. Place CSV files in data/ directory.")
        sys.exit(1)

    variant_names = list(VARIANTS.keys())

    # Run each variant per contract, store all results
    all_results = {}  # {variant_name: {root: BacktestResult}}
    for variant_name in variant_names:
        all_results[variant_name] = {}

    for root, bars in contract_bars.items():
        per_contract_results = {}
        for variant_name, kwargs in VARIANTS.items():
            result = run_variant(root, bars, variant_name, kwargs)
            per_contract_results[variant_name] = result
            all_results[variant_name][root] = result

        print_table(per_contract_results, variant_names, f"{root} — Independent Improvement Comparison")

    # ── Combined totals across all contracts ──
    if len(contract_bars) > 1:
        combined = {}
        for variant_name in variant_names:
            trades = []
            for r in all_results[variant_name].values():
                trades.extend(r.trades)
            combined_result = BacktestResult(symbol="ALL", trades=trades)
            combined[variant_name] = combined_result
        print_table(combined, variant_names, "COMBINED TOTALS (All Contracts)")

    # ── Print variant descriptions ──
    print(f"\n{'=' * 80}")
    print("  VARIANT DESCRIPTIONS (all build on Best Combo B)")
    print(f"{'=' * 80}")
    print("  Original Baseline  — Default params for reference")
    print("  Best Combo B       — Counter-mom + 2.5x elephant + push 8 (our best so far)")
    print("  + Skip Evening     — No trades 21:00-00:00 UTC (6% WR session)")
    print("  + Skip Sun         — No Sunday trades (0% WR)")
    print("  + Skip Thu/Fri/Sun — Only Mon-Wed trades (Mon/Tue carry the strategy)")
    print("  + Mon-Wed Only     — Strictest day filter")
    print("  + Max 40 Ticks     — Cap stop distance at 40 ticks")
    print("  + Max 75 Ticks     — Cap stop distance at 75 ticks")
    print("  + TimeStop 150     — Exit at market after 150 bars (~5 hrs) if no push exit")
    print("  + TimeStop 300     — Exit at market after 300 bars (~10 hrs)")
    print("  + Skip Eve+Sun     — Combined evening + Sunday filter")
    print("  + SkipEve+Sun+Max75— Evening + Sunday + max 75 tick stop")
    print("  ULTIMATE           — All filters: eve + sun + max75 + timestop300")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
