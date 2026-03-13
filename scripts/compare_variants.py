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
# Phase 1: original single-parameter tests
# Phase 2: data-driven patterns from analyze_patterns.py
VARIANTS = {
    "Baseline": {
        # Current defaults
    },
    "Counter-Momentum": {
        "require_counter_momentum": True,
    },
    "Counter-Mom + 2.5x": {
        "require_counter_momentum": True,
        "elephant_mult": 2.5,
    },
    "Counter-Mom + Push8": {
        "require_counter_momentum": True,
        "push_exit_count": 8,
    },
    "London (08-14 UTC)": {
        "tod_start_hour": 8,
        "tod_end_hour": 14,
    },
    "London+RTH (08-21 UTC)": {
        "tod_start_hour": 8,
        "tod_end_hour": 21,
    },
    "Skip Asia (08-24 UTC)": {
        "tod_start_hour": 8,
        "tod_end_hour": 0,
    },
    "Longs Only": {
        # allow_shorts handled separately
    },
    "Longs + Counter-Mom": {
        "require_counter_momentum": True,
        # allow_shorts handled separately
    },
    "Body 80% (relaxed)": {
        "min_body_range_ratio": 0.80,
    },
    "Body 95% (strict)": {
        "min_body_range_ratio": 0.95,
    },
    "Best Combo A": {
        # 2.5x + push 8 + skip narrow (top single variants)
        "elephant_mult": 2.5,
        "push_exit_count": 8,
        "skip_narrow": True,
    },
    "Best Combo B": {
        # counter-momentum + 2.5x + push 8
        "require_counter_momentum": True,
        "elephant_mult": 2.5,
        "push_exit_count": 8,
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
    allow_shorts = variant_name not in ("Longs Only", "Longs + Counter-Mom")

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
    print("  VARIANT DESCRIPTIONS")
    print(f"{'=' * 80}")
    print("  Baseline           — Default: elephant_mult=1.5, push_exit=6, all hours, shorts on")
    print("  Counter-Momentum   — Only enter when elephant bar opposes prior 3 bars' direction")
    print("  Counter-Mom + 2.5x — Counter-momentum + stricter elephant (2.5x avg body)")
    print("  Counter-Mom + Push8— Counter-momentum + exit after 8 pushes")
    print("  London (08-14)     — Trade only during London session")
    print("  London+RTH (08-21) — London + US RTH (skip Asia)")
    print("  Skip Asia (08-24)  — Skip Asia session (worst continuation rates)")
    print("  Longs Only         — No short entries")
    print("  Longs + Counter-Mom— Longs only + counter-momentum filter")
    print("  Body 80% (relaxed) — Lower body-to-range threshold (more signals)")
    print("  Body 95% (strict)  — Higher body-to-range threshold (fewer, cleaner signals)")
    print("  Best Combo A       — 2.5x elephant + push 8 + skip narrow")
    print("  Best Combo B       — Counter-mom + 2.5x elephant + push 8")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
