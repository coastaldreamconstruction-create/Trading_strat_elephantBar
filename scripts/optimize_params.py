#!/usr/bin/env python3
"""
Parameter optimization: Sweep key strategy parameters to find what improves P&L.

Tests:
  1. Elephant multiplier (1.5x, 2.0x, 2.5x, 3.0x)
  2. Push exit count (3, 4, 5, 6)
  3. Narrow threshold (0.5, 1.0, 1.5, 2.0 x ATR)
  4. Trailing stop on/off with different trigger/step values
  5. No-tail strictness (90%, 80%, 70% body-to-range)
  6. Skip narrow filter entirely
  7. Combined best params

Usage:
    python3 scripts/optimize_params.py
"""
import os
import sys
import numpy as np
from itertools import product

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.strategy.core import Bar, ElephantBarStrategy
from src.backtest.engine import Backtester, BacktestResult
from src import config


def generate_synthetic_bars(n_bars=18000, start_price=6000.0, tick_size=0.25, seed=42):
    """Generate realistic 2-min MES-like bars."""
    rng = np.random.default_rng(seed)
    bars = []
    price = start_price
    timestamp = 1706572800.0

    regime = 0
    regime_duration = 0
    regime_length = rng.integers(100, 500)

    for i in range(n_bars):
        timestamp += 120
        regime_duration += 1
        if regime_duration >= regime_length:
            regime = rng.integers(0, 3)
            regime_length = rng.integers(100, 500)
            regime_duration = 0

        base_vol = 1.5
        if regime == 0:
            drift = rng.normal(0, 0.1)
            vol = base_vol * rng.uniform(0.5, 1.0)
        elif regime == 1:
            drift = rng.uniform(0.2, 0.8)
            vol = base_vol * rng.uniform(0.8, 1.5)
        else:
            drift = rng.uniform(-0.8, -0.2)
            vol = base_vol * rng.uniform(0.8, 1.5)

        is_elephant = rng.random() < 0.02
        if is_elephant:
            vol *= rng.uniform(3.0, 5.0)
            drift *= rng.uniform(2.0, 4.0)

        open_price = price
        body = drift + rng.normal(0, vol)
        close_price = open_price + body

        wick_up = abs(rng.normal(0, vol * 0.3))
        wick_down = abs(rng.normal(0, vol * 0.3))

        if close_price > open_price:
            high = close_price + wick_up
            low = open_price - wick_down
            if is_elephant and rng.random() < 0.7:
                low = open_price - wick_down * 0.1
                high = close_price + wick_up * 0.1
        else:
            high = open_price + wick_up
            low = close_price - wick_down
            if is_elephant and rng.random() < 0.7:
                high = open_price + wick_up * 0.1
                low = close_price - wick_down * 0.1

        open_price = round(open_price / tick_size) * tick_size
        high = round(high / tick_size) * tick_size
        low = round(low / tick_size) * tick_size
        close_price = round(close_price / tick_size) * tick_size
        high = max(high, open_price, close_price)
        low = min(low, open_price, close_price)

        volume = float(rng.integers(100, 2000))
        if is_elephant:
            volume *= rng.uniform(2.0, 5.0)

        bars.append(Bar(
            timestamp=timestamp, open=open_price, high=high,
            low=low, close=close_price, volume=volume,
        ))
        price = close_price

    return bars


def run_backtest(bars, **kwargs):
    """Run a single backtest with given params, return result."""
    spec = config.CONTRACTS_2MIN["MES"]
    bt = Backtester(
        symbol="MES",
        tick_size=spec["tick_size"],
        tick_value=spec["tick_value"],
        allow_shorts=True,
        starting_capital=config.STARTING_CAPITAL,
        max_daily_loss=config.MAX_DAILY_LOSS,
        **kwargs,
    )
    return bt.run(bars)


def analyze_trades(result):
    """Compute detailed trade statistics."""
    if not result.trades:
        return {}

    winners = [t for t in result.trades if t.pnl > 0]
    losers = [t for t in result.trades if t.pnl <= 0]
    push_exits = [t for t in result.trades if t.exit_reason == "PUSH_EXIT"]
    stop_exits = [t for t in result.trades if t.exit_reason == "STOP_EXIT"]

    # Risk/reward ratio
    avg_win = sum(t.pnl for t in winners) / len(winners) if winners else 0
    avg_loss = abs(sum(t.pnl for t in losers) / len(losers)) if losers else 1

    # Average bars in trade (using timestamps)
    durations = [(t.exit_timestamp - t.entry_timestamp) / 120 for t in result.trades]
    avg_duration = sum(durations) / len(durations) if durations else 0

    # Consecutive losers
    max_consec_loss = 0
    curr_consec = 0
    for t in result.trades:
        if t.pnl <= 0:
            curr_consec += 1
            max_consec_loss = max(max_consec_loss, curr_consec)
        else:
            curr_consec = 0

    return {
        "rr_ratio": avg_win / avg_loss if avg_loss > 0 else 0,
        "avg_duration_bars": avg_duration,
        "push_exit_pct": len(push_exits) / len(result.trades) if result.trades else 0,
        "stop_exit_pct": len(stop_exits) / len(result.trades) if result.trades else 0,
        "max_consec_loss": max_consec_loss,
        "push_exit_avg_pnl": sum(t.pnl for t in push_exits) / len(push_exits) if push_exits else 0,
        "stop_exit_avg_pnl": sum(t.pnl for t in stop_exits) / len(stop_exits) if stop_exits else 0,
    }


def main():
    seeds = [0, 1, 2, 3, 4]
    all_bars = [generate_synthetic_bars(seed=s) for s in seeds]

    print("=" * 80)
    print("  PARAMETER OPTIMIZATION — Elephant Bar Strategy")
    print(f"  Testing across {len(seeds)} synthetic datasets (18,000 bars each)")
    print("=" * 80)

    # ── 1. Diagnose: Where are we losing money? ──
    print(f"\n{'─' * 80}")
    print("  DIAGNOSIS: Current strategy (push=3) trade breakdown")
    print(f"{'─' * 80}")

    for seed_idx, bars in enumerate(all_bars):
        r = run_backtest(bars, push_exit_count=3)
        stats = analyze_trades(r)
        print(f"\n  Seed {seeds[seed_idx]}: {r.total_trades} trades, P&L=${r.total_pnl:.2f}")
        if stats:
            print(f"    R:R ratio: {stats['rr_ratio']:.2f}")
            print(f"    Push exits: {stats['push_exit_pct']:.0%} (avg P&L ${stats['push_exit_avg_pnl']:.2f})")
            print(f"    Stop exits: {stats['stop_exit_pct']:.0%} (avg P&L ${stats['stop_exit_avg_pnl']:.2f})")
            print(f"    Max consecutive losses: {stats['max_consec_loss']}")
            print(f"    Avg trade duration: {stats['avg_duration_bars']:.0f} bars")

    # ── 2. Individual parameter sweeps ──
    sweeps = {
        "Push Exit Count": {"param": "push_exit_count", "values": [2, 3, 4, 5, 6, 8]},
        "Elephant Multiplier": {"param": "elephant_mult", "values": [1.5, 2.0, 2.5, 3.0]},
        "Narrow Threshold": {"param": "narrow_threshold", "values": [0.5, 0.75, 1.0, 1.5, 2.0]},
        "Skip Narrow Filter": {"param": "skip_narrow", "values": [False, True]},
        "Trailing Stop": {"param": "trailing_stop", "values": [False, True]},
    }

    sweep_results = {}

    for sweep_name, sweep_cfg in sweeps.items():
        print(f"\n{'═' * 80}")
        print(f"  SWEEP: {sweep_name}")
        print(f"{'═' * 80}")
        print(f"  {'Value':<12} {'Trades':>7} {'Win%':>7} {'P&L':>11} {'PF':>7} "
              f"{'R:R':>6} {'MaxDD':>10} {'AvgWin':>9} {'AvgLoss':>9}")
        print(f"  {'─' * 12} {'─' * 7} {'─' * 7} {'─' * 11} {'─' * 7} "
              f"{'─' * 6} {'─' * 10} {'─' * 9} {'─' * 9}")

        for val in sweep_cfg["values"]:
            kwargs = {sweep_cfg["param"]: val}
            total_trades = 0
            total_winners = 0
            total_pnl = 0.0
            total_dd = 0.0
            total_gross_win = 0.0
            total_gross_loss = 0.0
            n_winners = 0
            n_losers = 0

            for bars in all_bars:
                r = run_backtest(bars, **kwargs)
                total_trades += r.total_trades
                total_winners += len(r.winners)
                total_pnl += r.total_pnl
                total_dd += r.max_drawdown
                total_gross_win += r.gross_profit
                total_gross_loss += r.gross_loss
                n_winners += len(r.winners)
                n_losers += len(r.losers)

            wr = f"{total_winners / total_trades:.1%}" if total_trades > 0 else "N/A"
            pf = abs(total_gross_win / total_gross_loss) if total_gross_loss != 0 else 0
            avg_w = total_gross_win / n_winners if n_winners > 0 else 0
            avg_l = total_gross_loss / n_losers if n_losers > 0 else 0
            rr = abs(avg_w / avg_l) if avg_l != 0 else 0

            label = str(val)
            print(
                f"  {label:<12} {total_trades:>7} {wr:>7} "
                f"${total_pnl:>10,.2f} {pf:>7.2f} "
                f"{rr:>6.2f} ${total_dd:>9,.2f} "
                f"${avg_w:>8,.2f} ${avg_l:>8,.2f}"
            )

            sweep_results[(sweep_name, val)] = {
                "trades": total_trades, "pnl": total_pnl,
                "pf": pf, "wr": total_winners / total_trades if total_trades > 0 else 0,
            }

    # ── 3. Combined optimization: best params together ──
    print(f"\n{'═' * 80}")
    print("  COMBINED OPTIMIZATION — Top parameter combinations")
    print(f"{'═' * 80}")

    combos = [
        ("Default (push=3)", {}),
        ("Push=6", {"push_exit_count": 6}),
        ("Push=6 + Trail", {"push_exit_count": 6, "trailing_stop": True}),
        ("Push=4 + EM=2.5", {"push_exit_count": 4, "elephant_mult": 2.5}),
        ("Push=6 + EM=2.5", {"push_exit_count": 6, "elephant_mult": 2.5}),
        ("Push=6 + Narrow=1.5", {"push_exit_count": 6, "narrow_threshold": 1.5}),
        ("Push=6 + EM=1.5", {"push_exit_count": 6, "elephant_mult": 1.5}),
        ("Push=6 + NoNarrow", {"push_exit_count": 6, "skip_narrow": True}),
        ("Push=6 + Trail + EM=2.5", {"push_exit_count": 6, "trailing_stop": True, "elephant_mult": 2.5}),
        ("Push=5 + EM=2.0 + Narrow=1.5", {"push_exit_count": 5, "elephant_mult": 2.0, "narrow_threshold": 1.5}),
    ]

    print(f"  {'Combo':<32} {'Trades':>7} {'Win%':>7} {'P&L':>11} {'PF':>7} {'MaxDD':>10}")
    print(f"  {'─' * 32} {'─' * 7} {'─' * 7} {'─' * 11} {'─' * 7} {'─' * 10}")

    for name, kwargs in combos:
        total_trades = 0
        total_winners = 0
        total_pnl = 0.0
        total_dd = 0.0
        total_gw = 0.0
        total_gl = 0.0

        for bars in all_bars:
            r = run_backtest(bars, **kwargs)
            total_trades += r.total_trades
            total_winners += len(r.winners)
            total_pnl += r.total_pnl
            total_dd += r.max_drawdown
            total_gw += r.gross_profit
            total_gl += r.gross_loss

        wr = f"{total_winners / total_trades:.1%}" if total_trades > 0 else "N/A"
        pf = abs(total_gw / total_gl) if total_gl != 0 else 0
        print(
            f"  {name:<32} {total_trades:>7} {wr:>7} "
            f"${total_pnl:>10,.2f} {pf:>7.2f} ${total_dd:>9,.2f}"
        )

    print(f"{'═' * 80}")
    print()
    print("  KEY INSIGHTS:")
    print("  - Higher push exit = lets winners run longer (key P&L driver)")
    print("  - Elephant multiplier sweet spot: balance signal frequency vs quality")
    print("  - Trailing stop: locks in gains on big moves, may cut some winners short")
    print("  - Narrow threshold: wider = more trades, tighter = higher quality")
    print()


if __name__ == "__main__":
    main()
