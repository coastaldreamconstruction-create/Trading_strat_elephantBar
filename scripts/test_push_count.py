#!/usr/bin/env python3
"""
A/B Test: PUSH_EXIT_COUNT = 3 vs 6

Generates realistic synthetic 2-min futures bars (trending + ranging regimes)
and compares strategy performance with different push exit thresholds.

Usage:
    python3 scripts/test_push_count.py

    # With saved CSVs (real data)
    python3 scripts/test_push_count.py --use-csv
"""
import argparse
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.strategy.core import Bar
from src.backtest.engine import Backtester, BacktestResult
from src import config


def generate_synthetic_bars(
    n_bars: int = 18000,
    start_price: float = 6000.0,
    tick_size: float = 0.25,
    seed: int = 42,
) -> list[Bar]:
    """
    Generate realistic 2-min MES-like bars with:
    - Trending regimes (sustained moves)
    - Ranging regimes (choppy sideways)
    - Occasional elephant bars (large momentum candles)
    - Realistic volume patterns
    """
    rng = np.random.default_rng(seed)
    bars = []
    price = start_price
    timestamp = 1706572800.0  # 2024-01-30 00:00:00 UTC

    # Regime: 0 = ranging, 1 = trending up, 2 = trending down
    regime = 0
    regime_duration = 0
    regime_length = rng.integers(100, 500)

    for i in range(n_bars):
        timestamp += 120  # 2-min bars

        # Switch regime periodically
        regime_duration += 1
        if regime_duration >= regime_length:
            regime = rng.integers(0, 3)
            regime_length = rng.integers(100, 500)
            regime_duration = 0

        # Base volatility (MES-like: ~2-5 points per 2-min bar)
        base_vol = 1.5

        # Regime-dependent drift
        if regime == 0:  # Ranging
            drift = rng.normal(0, 0.1)
            vol = base_vol * rng.uniform(0.5, 1.0)
        elif regime == 1:  # Trending up
            drift = rng.uniform(0.2, 0.8)
            vol = base_vol * rng.uniform(0.8, 1.5)
        else:  # Trending down
            drift = rng.uniform(-0.8, -0.2)
            vol = base_vol * rng.uniform(0.8, 1.5)

        # Occasional elephant bars (~2% of bars)
        is_elephant_bar = rng.random() < 0.02
        if is_elephant_bar:
            vol *= rng.uniform(3.0, 5.0)
            drift *= rng.uniform(2.0, 4.0)

        # Generate OHLC
        open_price = price
        body = drift + rng.normal(0, vol)
        close_price = open_price + body

        # Wicks
        wick_up = abs(rng.normal(0, vol * 0.3))
        wick_down = abs(rng.normal(0, vol * 0.3))

        if close_price > open_price:  # Bullish
            high = close_price + wick_up
            low = open_price - wick_down
            # For elephant bars, minimize wicks (no-tail characteristic)
            if is_elephant_bar and rng.random() < 0.7:
                low = open_price - wick_down * 0.1
                high = close_price + wick_up * 0.1
        else:  # Bearish
            high = open_price + wick_up
            low = close_price - wick_down
            if is_elephant_bar and rng.random() < 0.7:
                high = open_price + wick_up * 0.1
                low = close_price - wick_down * 0.1

        # Round to tick size
        open_price = round(open_price / tick_size) * tick_size
        high = round(high / tick_size) * tick_size
        low = round(low / tick_size) * tick_size
        close_price = round(close_price / tick_size) * tick_size

        # Ensure OHLC consistency
        high = max(high, open_price, close_price)
        low = min(low, open_price, close_price)

        volume = float(rng.integers(100, 2000))
        if is_elephant_bar:
            volume *= rng.uniform(2.0, 5.0)

        bars.append(Bar(
            timestamp=timestamp,
            open=open_price,
            high=high,
            low=low,
            close=close_price,
            volume=volume,
        ))

        price = close_price

    return bars


def load_real_bars(contract: str) -> list[Bar]:
    """Try to load real CSV data."""
    from scripts.run_backtest import load_bars_from_csv
    data_dir = "data"
    if not os.path.isdir(data_dir):
        return []
    for f in sorted(os.listdir(data_dir), reverse=True):
        if f.startswith(contract + "_") and f.endswith(".csv"):
            return load_bars_from_csv(os.path.join(data_dir, f))
    return []


def run_comparison(bars: list[Bar], symbol: str, label: str):
    """Run push_count = 3 vs 6 comparison on given bars."""
    spec = config.CONTRACTS_2MIN[symbol]

    variants = {
        "Push Exit = 3": {"push_exit_count": 3},
        "Push Exit = 6": {"push_exit_count": 6},
    }

    results = {}
    for name, kwargs in variants.items():
        bt = Backtester(
            symbol=symbol,
            tick_size=spec["tick_size"],
            tick_value=spec["tick_value"],
            allow_shorts=True,
            starting_capital=config.STARTING_CAPITAL,
            max_daily_loss=config.MAX_DAILY_LOSS,
            **kwargs,
        )
        results[name] = bt.run(bars)

    # Print comparison
    print(f"\n{'═' * 72}")
    print(f"  {label} — {symbol} ({len(bars):,} bars)")
    print(f"{'═' * 72}")
    print(f"  {'Variant':<20} {'Trades':>7} {'Win%':>7} {'P&L':>11} {'PF':>7} "
          f"{'AvgWin':>9} {'AvgLoss':>9} {'MaxDD':>10}")
    print(f"  {'─' * 20} {'─' * 7} {'─' * 7} {'─' * 11} {'─' * 7} "
          f"{'─' * 9} {'─' * 9} {'─' * 10}")

    for name, r in results.items():
        pf = f"{r.profit_factor:.2f}" if r.total_trades > 0 else "N/A"
        wr = f"{r.win_rate:.1%}" if r.total_trades > 0 else "N/A"
        aw = f"${r.avg_winner:,.2f}" if r.winners else "N/A"
        al = f"${r.avg_loser:,.2f}" if r.losers else "N/A"
        print(
            f"  {name:<20} {r.total_trades:>7} {wr:>7} "
            f"${r.total_pnl:>10,.2f} {pf:>7} "
            f"{aw:>9} {al:>9} ${r.max_drawdown:>9,.2f}"
        )

    # Print trade-by-trade detail for shorter lists
    for name, r in results.items():
        if 0 < r.total_trades <= 30:
            print(f"\n  {name} — Trade Detail:")
            print(f"  {'#':>3} {'Dir':<6} {'Entry':>10} {'Exit':>10} {'P&L':>10} {'Reason':<12}")
            print(f"  {'─'*3} {'─'*6} {'─'*10} {'─'*10} {'─'*10} {'─'*12}")
            for i, t in enumerate(r.trades, 1):
                print(
                    f"  {i:>3} {t.direction:<6} {t.entry_price:>10.2f} "
                    f"{t.exit_price:>10.2f} ${t.pnl:>9.2f} {t.exit_reason:<12}"
                )

    return results


def main():
    parser = argparse.ArgumentParser(description="Test push exit count: 3 vs 6")
    parser.add_argument("--use-csv", action="store_true", help="Use saved CSV data if available")
    parser.add_argument("--seeds", type=int, default=3, help="Number of synthetic data seeds to test")
    args = parser.parse_args()

    print("=" * 72)
    print("  PUSH EXIT COUNT COMPARISON: 3 vs 6")
    print("  Strategy: Elephant Bar Breakout (narrow SMA + no tail)")
    print("=" * 72)

    # Try real data first if requested
    if args.use_csv:
        for symbol in ["MES", "MNQ", "MYM", "MCL", "MGC"]:
            bars = load_real_bars(symbol)
            if bars:
                run_comparison(bars, symbol, "Real Data")
            else:
                print(f"\n  No CSV data for {symbol}, skipping.")

    # Always run synthetic tests for reproducible comparison
    print(f"\n{'=' * 72}")
    print("  SYNTHETIC DATA TESTS (reproducible)")
    print(f"{'=' * 72}")

    all_results = {}
    for seed in range(args.seeds):
        bars = generate_synthetic_bars(n_bars=18000, seed=seed)
        results = run_comparison(bars, "MES", f"Synthetic Seed {seed}")
        for name, r in results.items():
            if name not in all_results:
                all_results[name] = {"trades": 0, "winners": 0, "pnl": 0.0, "dd": 0.0}
            all_results[name]["trades"] += r.total_trades
            all_results[name]["winners"] += len(r.winners)
            all_results[name]["pnl"] += r.total_pnl
            all_results[name]["dd"] += r.max_drawdown

    # Aggregate summary
    print(f"\n{'═' * 72}")
    print(f"  AGGREGATE ACROSS {args.seeds} SYNTHETIC DATASETS")
    print(f"{'═' * 72}")
    print(f"  {'Variant':<20} {'Trades':>7} {'Win%':>7} {'Total P&L':>12} {'Avg DD':>10}")
    print(f"  {'─' * 20} {'─' * 7} {'─' * 7} {'─' * 12} {'─' * 10}")

    for name, agg in all_results.items():
        wr = f"{agg['winners'] / agg['trades']:.1%}" if agg['trades'] > 0 else "N/A"
        avg_dd = agg['dd'] / args.seeds
        print(
            f"  {name:<20} {agg['trades']:>7} {wr:>7} "
            f"${agg['pnl']:>11,.2f} ${avg_dd:>9,.2f}"
        )

    print(f"{'═' * 72}")
    print()


if __name__ == "__main__":
    main()
