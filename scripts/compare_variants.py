#!/usr/bin/env python3
"""
A/B Test: Compare strategy variants to isolate the effect of each change.

Tests:
  Baseline — 6 pushes, fixed stop (current settings)
  Test A   — 6 pushes, trailing stop
  Test B   — 5 pushes, fixed stop
  Test C   — 4 pushes, fixed stop

Usage:
    # Uses saved CSVs (no API calls needed)
    python3 scripts/compare_variants.py

    # Specify a single contract
    python3 scripts/compare_variants.py --contract MES
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.run_backtest import load_bars_from_csv
from src.backtest.engine import Backtester, BacktestResult
from src import config


# Drop SICK from comparison — silver doesn't suit this strategy
CONTRACTS = ["MES", "MNQ", "MYM", "MCL", "MGC"]

VARIANTS = {
    "Baseline (6 push, fixed stop)": {
        "push_exit_count": 6,
        "trailing_stop": False,
    },
    "Test A (6 push, trailing stop)": {
        "push_exit_count": 6,
        "trailing_stop": True,
        "trail_trigger_atr": 1.0,
        "trail_step_atr": 0.5,
    },
    "Test B (5 push, fixed stop)": {
        "push_exit_count": 5,
        "trailing_stop": False,
    },
    "Test C (4 push, fixed stop)": {
        "push_exit_count": 4,
        "trailing_stop": False,
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
        # Also check for SIL CSV when running SICK
        if root == "SICK" and f.startswith("SIL_") and f.endswith(".csv"):
            return os.path.join(data_dir, f)
    return ""


def run_variant(root: str, bars, variant_kwargs: dict) -> BacktestResult:
    """Run a single backtest variant."""
    spec = config.CONTRACTS_2MIN.get(root)
    if spec is None:
        return BacktestResult(symbol=root)

    bt = Backtester(
        symbol=root,
        tick_size=spec["tick_size"],
        tick_value=spec["tick_value"],
        allow_shorts=True,
        starting_capital=config.STARTING_CAPITAL,
        max_daily_loss=config.MAX_DAILY_LOSS,
        **variant_kwargs,
    )
    return bt.run(bars)


def main():
    parser = argparse.ArgumentParser(description="Compare strategy variants")
    parser.add_argument("--contract", default=None, help="Single contract to test")
    args = parser.parse_args()

    contracts = [args.contract] if args.contract else CONTRACTS

    # Load bars for each contract
    contract_bars = {}
    for root in contracts:
        csv_path = find_csv(root)
        if not csv_path:
            print(f"WARNING: No CSV found for {root}. Run backtest with --save-csv first.")
            continue
        contract_bars[root] = load_bars_from_csv(csv_path)
        print(f"Loaded {len(contract_bars[root]):,} bars for {root} from {csv_path}")

    if not contract_bars:
        print("No data found. Run: python3 scripts/run_backtest.py --all --save-csv")
        sys.exit(1)

    print()

    # Run each variant across all contracts
    results = {}  # {variant_name: {root: BacktestResult}}
    for variant_name, kwargs in VARIANTS.items():
        results[variant_name] = {}
        for root, bars in contract_bars.items():
            results[variant_name][root] = run_variant(root, bars, kwargs)

    # ── Print per-contract comparison ──
    for root in contract_bars:
        print(f"\n{'═' * 70}")
        print(f"  {root} — Variant Comparison")
        print(f"{'═' * 70}")
        print(f"  {'Variant':<35} {'Trades':>6} {'Win%':>6} {'P&L':>10} {'PF':>6} {'MaxDD':>10}")
        print(f"  {'─' * 35} {'─' * 6} {'─' * 6} {'─' * 10} {'─' * 6} {'─' * 10}")

        for variant_name in VARIANTS:
            r = results[variant_name][root]
            pf = f"{r.profit_factor:.2f}" if r.total_trades > 0 else "N/A"
            wr = f"{r.win_rate:.1%}" if r.total_trades > 0 else "N/A"
            print(
                f"  {variant_name:<35} {r.total_trades:>6} {wr:>6} "
                f"${r.total_pnl:>9,.2f} {pf:>6} ${r.max_drawdown:>9,.2f}"
            )

    # ── Print combined totals ──
    print(f"\n{'═' * 70}")
    print(f"  COMBINED TOTALS (All Contracts)")
    print(f"{'═' * 70}")
    print(f"  {'Variant':<35} {'Trades':>6} {'Win%':>6} {'P&L':>10} {'MaxDD':>10}")
    print(f"  {'─' * 35} {'─' * 6} {'─' * 6} {'─' * 10} {'─' * 10}")

    for variant_name in VARIANTS:
        total_trades = sum(r.total_trades for r in results[variant_name].values())
        total_winners = sum(len(r.winners) for r in results[variant_name].values())
        total_pnl = sum(r.total_pnl for r in results[variant_name].values())
        total_dd = sum(r.max_drawdown for r in results[variant_name].values())
        wr = f"{total_winners / total_trades:.1%}" if total_trades > 0 else "N/A"
        print(
            f"  {variant_name:<35} {total_trades:>6} {wr:>6} "
            f"${total_pnl:>9,.2f} ${total_dd:>9,.2f}"
        )

    print(f"{'═' * 70}")
    print()


if __name__ == "__main__":
    main()
