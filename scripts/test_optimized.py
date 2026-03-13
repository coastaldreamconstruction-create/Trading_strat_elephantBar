#!/usr/bin/env python3
"""
Head-to-head test: Original params vs Optimized params

Original:  push=3, elephant_mult=2.0, narrow=on
Optimized: push=6, elephant_mult=1.5, narrow=on

Tests across all 6 contracts with contract-specific tick sizes/values,
using multiple synthetic datasets with different market conditions.

Usage:
    python3 scripts/test_optimized.py
"""
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.strategy.core import Bar
from src.backtest.engine import Backtester, BacktestResult
from src import config


# Contract-specific synthetic data params (realistic price levels & volatility)
CONTRACT_PROFILES = {
    "MES":  {"start": 6000, "base_vol": 1.5,  "tick_size": 0.25},
    "MNQ":  {"start": 21000, "base_vol": 8.0, "tick_size": 0.25},
    "MYM":  {"start": 44000, "base_vol": 15.0, "tick_size": 1.00},
    "MCL":  {"start": 72.0,  "base_vol": 0.08, "tick_size": 0.01},
    "MGC":  {"start": 2950,  "base_vol": 2.0,  "tick_size": 0.10},
    "SICK": {"start": 24.0,  "base_vol": 0.05, "tick_size": 0.01},
}


def generate_bars(profile, n_bars=18000, seed=42):
    """Generate realistic 2-min bars for a given contract profile."""
    rng = np.random.default_rng(seed)
    bars = []
    price = profile["start"]
    tick = profile["tick_size"]
    base_vol = profile["base_vol"]
    ts = 1706572800.0

    regime = 0
    regime_dur = 0
    regime_len = rng.integers(100, 500)

    for _ in range(n_bars):
        ts += 120
        regime_dur += 1
        if regime_dur >= regime_len:
            regime = rng.integers(0, 3)
            regime_len = rng.integers(100, 500)
            regime_dur = 0

        if regime == 0:
            drift = rng.normal(0, base_vol * 0.05)
            vol = base_vol * rng.uniform(0.5, 1.0)
        elif regime == 1:
            drift = base_vol * rng.uniform(0.1, 0.4)
            vol = base_vol * rng.uniform(0.8, 1.5)
        else:
            drift = -base_vol * rng.uniform(0.1, 0.4)
            vol = base_vol * rng.uniform(0.8, 1.5)

        is_elephant = rng.random() < 0.02
        if is_elephant:
            vol *= rng.uniform(3.0, 5.0)
            drift *= rng.uniform(2.0, 4.0)

        o = price
        body = drift + rng.normal(0, vol)
        c = o + body

        wu = abs(rng.normal(0, vol * 0.3))
        wd = abs(rng.normal(0, vol * 0.3))

        if c > o:
            h, l = c + wu, o - wd
            if is_elephant and rng.random() < 0.7:
                l = o - wd * 0.1
                h = c + wu * 0.1
        else:
            h, l = o + wu, c - wd
            if is_elephant and rng.random() < 0.7:
                h = o + wu * 0.1
                l = c - wd * 0.1

        o = round(o / tick) * tick
        h = round(h / tick) * tick
        l = round(l / tick) * tick
        c = round(c / tick) * tick
        h = max(h, o, c)
        l = min(l, o, c)

        vol_shares = float(rng.integers(100, 2000))
        if is_elephant:
            vol_shares *= rng.uniform(2, 5)

        bars.append(Bar(timestamp=ts, open=o, high=h, low=l, close=c, volume=vol_shares))
        price = c

    return bars


def run_bt(bars, symbol, **kwargs):
    spec = config.CONTRACTS_2MIN.get(symbol)
    if not spec:
        return BacktestResult(symbol=symbol)
    bt = Backtester(
        symbol=symbol,
        tick_size=spec["tick_size"],
        tick_value=spec["tick_value"],
        allow_shorts=True,
        starting_capital=config.STARTING_CAPITAL,
        max_daily_loss=config.MAX_DAILY_LOSS,
        **kwargs,
    )
    return bt.run(bars)


def main():
    seeds = [0, 1, 2, 3, 4]
    contracts = ["MES", "MNQ", "MYM", "MCL", "MGC", "SICK"]

    variants = {
        "Original (push=3, EM=2.0)": {"push_exit_count": 3, "elephant_mult": 2.0},
        "Optimized (push=6, EM=1.5)": {"push_exit_count": 6, "elephant_mult": 1.5},
    }

    print("=" * 85)
    print("  HEAD-TO-HEAD: Original vs Optimized Parameters")
    print(f"  {len(seeds)} synthetic datasets x {len(contracts)} contracts = {len(seeds)*len(contracts)} backtests per variant")
    print("=" * 85)

    # Per-contract results
    contract_totals = {v: {} for v in variants}

    for symbol in contracts:
        profile = CONTRACT_PROFILES[symbol]

        print(f"\n{'═' * 85}")
        print(f"  {symbol} (start=${profile['start']}, tick={profile['tick_size']})")
        print(f"{'═' * 85}")
        print(f"  {'Variant':<30} {'Trades':>7} {'Win%':>7} {'P&L':>12} {'PF':>7} "
              f"{'AvgWin':>9} {'AvgLoss':>9} {'MaxDD':>10}")
        print(f"  {'─'*30} {'─'*7} {'─'*7} {'─'*12} {'─'*7} {'─'*9} {'─'*9} {'─'*10}")

        for vname, vkwargs in variants.items():
            tt = tw = 0
            tpnl = tdd = tgw = tgl = 0.0
            nw = nl = 0

            for seed in seeds:
                bars = generate_bars(profile, seed=seed)
                r = run_bt(bars, symbol, **vkwargs)
                tt += r.total_trades
                tw += len(r.winners)
                tpnl += r.total_pnl
                tdd += r.max_drawdown
                tgw += r.gross_profit
                tgl += r.gross_loss
                nw += len(r.winners)
                nl += len(r.losers)

            wr = f"{tw/tt:.1%}" if tt > 0 else "N/A"
            pf = abs(tgw/tgl) if tgl != 0 else 0
            aw = tgw/nw if nw > 0 else 0
            al = tgl/nl if nl > 0 else 0

            print(f"  {vname:<30} {tt:>7} {wr:>7} ${tpnl:>11,.2f} {pf:>7.2f} "
                  f"${aw:>8,.2f} ${al:>8,.2f} ${tdd:>9,.2f}")

            contract_totals[vname][symbol] = {
                "trades": tt, "winners": tw, "pnl": tpnl,
                "dd": tdd, "gw": tgw, "gl": tgl,
            }

    # Grand totals
    print(f"\n{'═' * 85}")
    print("  GRAND TOTAL — All Contracts Combined")
    print(f"{'═' * 85}")
    print(f"  {'Variant':<30} {'Trades':>7} {'Win%':>7} {'P&L':>12} {'PF':>7} {'MaxDD':>10}")
    print(f"  {'─'*30} {'─'*7} {'─'*7} {'─'*12} {'─'*7} {'─'*10}")

    for vname in variants:
        data = contract_totals[vname]
        tt = sum(d["trades"] for d in data.values())
        tw = sum(d["winners"] for d in data.values())
        tpnl = sum(d["pnl"] for d in data.values())
        tdd = sum(d["dd"] for d in data.values())
        tgw = sum(d["gw"] for d in data.values())
        tgl = sum(d["gl"] for d in data.values())

        wr = f"{tw/tt:.1%}" if tt > 0 else "N/A"
        pf = abs(tgw/tgl) if tgl != 0 else 0

        print(f"  {vname:<30} {tt:>7} {wr:>7} ${tpnl:>11,.2f} {pf:>7.2f} ${tdd:>9,.2f}")

    # Improvement summary
    orig = contract_totals["Original (push=3, EM=2.0)"]
    opti = contract_totals["Optimized (push=6, EM=1.5)"]
    orig_pnl = sum(d["pnl"] for d in orig.values())
    opti_pnl = sum(d["pnl"] for d in opti.values())
    improvement = opti_pnl - orig_pnl
    pct = (improvement / abs(orig_pnl) * 100) if orig_pnl != 0 else float('inf')

    print(f"\n  {'─'*50}")
    print(f"  P&L improvement: ${improvement:,.2f} ({pct:+.0f}%)")
    print(f"  {'─'*50}")

    # Per-contract breakdown
    print(f"\n  Per-contract P&L comparison:")
    print(f"  {'Contract':<10} {'Original':>12} {'Optimized':>12} {'Delta':>12} {'Better?':>10}")
    print(f"  {'─'*10} {'─'*12} {'─'*12} {'─'*12} {'─'*10}")
    for symbol in contracts:
        o = orig[symbol]["pnl"]
        n = opti[symbol]["pnl"]
        delta = n - o
        better = "YES" if delta > 0 else "no"
        print(f"  {symbol:<10} ${o:>11,.2f} ${n:>11,.2f} ${delta:>11,.2f} {better:>10}")

    print(f"{'═' * 85}")
    print()


if __name__ == "__main__":
    main()
