#!/usr/bin/env python3
"""
Deep pattern analysis on real futures data.
Examines elephant bar characteristics, volume patterns, time-of-day effects,
momentum context, and win/loss patterns to find exploitable edges.
"""
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.run_backtest import load_bars_from_csv
from src.strategy.core import Bar, ElephantBarStrategy, Signal
from src.backtest.engine import Backtester, BacktestResult
from src import config


CONTRACTS = ["MES", "MNQ", "MYM", "MCL", "MGC", "MSI"]


def find_csv(root: str) -> str:
    data_dir = "data"
    for f in sorted(os.listdir(data_dir), reverse=True):
        if f.startswith(root + "_") and f.endswith(".csv") and "2min" in f:
            return os.path.join(data_dir, f)
    return ""


def analyze_elephant_bars(root: str, bars: list[Bar]):
    """Find all elephant bars and analyze their characteristics."""
    strategy = ElephantBarStrategy(
        symbol=root,
        tick_size=config.CONTRACTS_2MIN[root]["tick_size"],
    )

    elephant_bars = []
    for i, bar in enumerate(bars):
        strategy.bars.append(bar)
        if len(strategy.bars) < strategy.sma_slow_period + 1:
            continue

        avg_body = strategy._avg_body()
        atr = strategy._atr()
        sma_fast = strategy._sma(strategy.sma_fast_period)
        sma_slow = strategy._sma(strategy.sma_slow_period)

        if avg_body and atr and avg_body > 0:
            body_ratio = bar.body / avg_body
            if body_ratio >= 1.5:  # elephant bar
                try:
                    hour = datetime.fromtimestamp(bar.timestamp, tz=timezone.utc).hour
                except Exception:
                    hour = -1

                # Check what happens in the next N bars
                future_bars = bars[i+1:i+11] if i+10 < len(bars) else bars[i+1:]
                if future_bars:
                    if bar.is_bullish:
                        max_favorable = max(b.high for b in future_bars) - bar.close
                        max_adverse = bar.close - min(b.low for b in future_bars)
                    else:
                        max_favorable = bar.close - min(b.low for b in future_bars)
                        max_adverse = max(b.high for b in future_bars) - bar.close
                else:
                    max_favorable = 0
                    max_adverse = 0

                narrow = strategy._is_narrow(sma_fast, sma_slow, atr) if sma_fast and sma_slow else False
                no_tail = bar.is_no_tail

                elephant_bars.append({
                    "bar": bar,
                    "body_ratio": body_ratio,
                    "hour": hour,
                    "volume": bar.volume,
                    "atr": atr,
                    "direction": "BULL" if bar.is_bullish else "BEAR",
                    "narrow": narrow,
                    "no_tail": no_tail,
                    "max_favorable": max_favorable,
                    "max_adverse": max_adverse,
                    "favorable_ratio": max_favorable / max_adverse if max_adverse > 0 else float("inf"),
                    "body_to_range": bar.body / bar.full_range if bar.full_range > 0 else 0,
                    "volume_ratio": bar.volume / (sum(b.volume for b in bars[max(0,i-20):i]) / max(1, min(20, i))),
                })

    return elephant_bars


def print_section(title):
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print(f"{'=' * 80}")


def main():
    all_elephants = {}

    for root in CONTRACTS:
        csv_path = find_csv(root)
        if not csv_path:
            continue
        bars = load_bars_from_csv(csv_path)
        elephants = analyze_elephant_bars(root, bars)
        all_elephants[root] = elephants
        print(f"{root}: {len(elephants)} elephant bars found in {len(bars)} bars")

    # ══════════════════════════════════════════════
    # 1. VOLUME ANALYSIS
    # ══════════════════════════════════════════════
    print_section("1. VOLUME FILTER — Do high-volume elephant bars perform better?")
    for root, elephants in all_elephants.items():
        if not elephants:
            continue
        high_vol = [e for e in elephants if e["volume_ratio"] >= 2.0]
        low_vol = [e for e in elephants if e["volume_ratio"] < 2.0]

        def avg_ratio(lst):
            ratios = [e["favorable_ratio"] for e in lst if e["favorable_ratio"] != float("inf")]
            return sum(ratios) / len(ratios) if ratios else 0

        def continuation_rate(lst):
            good = [e for e in lst if e["max_favorable"] > e["max_adverse"]]
            return len(good) / len(lst) if lst else 0

        print(f"\n  {root}:")
        print(f"    High volume (>=2x avg):  {len(high_vol):>4} bars | continuation: {continuation_rate(high_vol):.1%} | avg fav/adv ratio: {avg_ratio(high_vol):.2f}")
        print(f"    Low volume (<2x avg):    {len(low_vol):>4} bars | continuation: {continuation_rate(low_vol):.1%} | avg fav/adv ratio: {avg_ratio(low_vol):.2f}")

    # ══════════════════════════════════════════════
    # 2. TIME OF DAY ANALYSIS
    # ══════════════════════════════════════════════
    print_section("2. TIME OF DAY — When do elephant bars have the best follow-through?")
    sessions = {
        "Asia (00-08 UTC)": range(0, 8),
        "London (08-14 UTC)": range(8, 14),
        "US RTH (14-21 UTC)": range(14, 21),
        "US Evening (21-00 UTC)": range(21, 24),
    }

    for root, elephants in all_elephants.items():
        if not elephants:
            continue
        print(f"\n  {root}:")
        for session_name, hours in sessions.items():
            session_bars = [e for e in elephants if e["hour"] in hours]
            if not session_bars:
                print(f"    {session_name:<25} {'0 bars':>8}")
                continue
            good = [e for e in session_bars if e["max_favorable"] > e["max_adverse"]]
            rate = len(good) / len(session_bars)
            avg_fav = sum(e["max_favorable"] for e in session_bars) / len(session_bars)
            print(f"    {session_name:<25} {len(session_bars):>4} bars | continuation: {rate:.1%} | avg favorable move: {avg_fav:.2f}")

    # ══════════════════════════════════════════════
    # 3. BODY-TO-RANGE RATIO (tail analysis)
    # ══════════════════════════════════════════════
    print_section("3. BODY-TO-RANGE RATIO — Is the 90% no-tail threshold too strict?")
    thresholds = [0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
    for root, elephants in all_elephants.items():
        if not elephants:
            continue
        print(f"\n  {root}:")
        for thresh in thresholds:
            qualified = [e for e in elephants if e["body_to_range"] >= thresh]
            if not qualified:
                print(f"    >= {thresh:.0%} body:  {0:>4} bars")
                continue
            good = [e for e in qualified if e["max_favorable"] > e["max_adverse"]]
            rate = len(good) / len(qualified)
            print(f"    >= {thresh:.0%} body:  {len(qualified):>4} bars | continuation: {rate:.1%}")

    # ══════════════════════════════════════════════
    # 4. ELEPHANT MULTIPLIER SWEET SPOT
    # ══════════════════════════════════════════════
    print_section("4. ELEPHANT MULTIPLIER — What body_ratio threshold gives best edge?")
    mult_thresholds = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
    for root, elephants in all_elephants.items():
        if not elephants:
            continue
        print(f"\n  {root}:")
        for mult in mult_thresholds:
            qualified = [e for e in elephants if e["body_ratio"] >= mult]
            if not qualified:
                print(f"    >= {mult:.1f}x:  {0:>4} bars")
                continue
            good = [e for e in qualified if e["max_favorable"] > e["max_adverse"]]
            rate = len(good) / len(qualified)
            avg_fav = sum(e["max_favorable"] for e in qualified) / len(qualified)
            print(f"    >= {mult:.1f}x:  {len(qualified):>4} bars | continuation: {rate:.1%} | avg favorable: {avg_fav:.2f}")

    # ══════════════════════════════════════════════
    # 5. DIRECTION BIAS
    # ══════════════════════════════════════════════
    print_section("5. DIRECTION — Do bullish or bearish elephant bars perform better?")
    for root, elephants in all_elephants.items():
        if not elephants:
            continue
        bulls = [e for e in elephants if e["direction"] == "BULL"]
        bears = [e for e in elephants if e["direction"] == "BEAR"]

        def stats(lst, label):
            if not lst:
                return f"    {label:<10} 0 bars"
            good = [e for e in lst if e["max_favorable"] > e["max_adverse"]]
            rate = len(good) / len(lst)
            avg_fav = sum(e["max_favorable"] for e in lst) / len(lst)
            avg_adv = sum(e["max_adverse"] for e in lst) / len(lst)
            return f"    {label:<10} {len(lst):>4} bars | continuation: {rate:.1%} | avg favorable: {avg_fav:.4f} | avg adverse: {avg_adv:.4f}"

        print(f"\n  {root}:")
        print(stats(bulls, "Bullish"))
        print(stats(bears, "Bearish"))

    # ══════════════════════════════════════════════
    # 6. NARROW + ELEPHANT COMBO vs JUST ELEPHANT
    # ══════════════════════════════════════════════
    print_section("6. NARROW SMA FILTER — Does requiring narrow SMAs actually help?")
    for root, elephants in all_elephants.items():
        if not elephants:
            continue
        with_narrow = [e for e in elephants if e["narrow"] and e["no_tail"]]
        without_narrow = [e for e in elephants if not e["narrow"] and e["no_tail"]]
        just_elephant = [e for e in elephants if e["no_tail"]]

        def cont_rate(lst):
            if not lst:
                return 0, 0
            good = [e for e in lst if e["max_favorable"] > e["max_adverse"]]
            return len(good) / len(lst), len(lst)

        r1, n1 = cont_rate(with_narrow)
        r2, n2 = cont_rate(without_narrow)
        r3, n3 = cont_rate(just_elephant)

        print(f"\n  {root}:")
        print(f"    Narrow + Elephant + NoTail:    {n1:>4} signals | continuation: {r1:.1%}")
        print(f"    NOT Narrow + Elephant + NoTail: {n2:>4} signals | continuation: {r2:.1%}")
        print(f"    Any Elephant + NoTail:          {n3:>4} signals | continuation: {r3:.1%}")

    # ══════════════════════════════════════════════
    # 7. CONSECUTIVE BARS / MOMENTUM CONTEXT
    # ══════════════════════════════════════════════
    print_section("7. MOMENTUM CONTEXT — Does prior bar direction matter?")
    for root in CONTRACTS:
        csv_path = find_csv(root)
        if not csv_path:
            continue
        bars = load_bars_from_csv(csv_path)
        elephants = all_elephants.get(root, [])
        if not elephants:
            continue

        # Check if the 3 bars before the elephant were in same direction
        strategy = ElephantBarStrategy(
            symbol=root,
            tick_size=config.CONTRACTS_2MIN[root]["tick_size"],
        )
        for bar in bars:
            strategy.bars.append(bar)

        with_momentum = []
        against_momentum = []

        for e in elephants:
            idx = None
            for i, b in enumerate(strategy.bars):
                if b.timestamp == e["bar"].timestamp:
                    idx = i
                    break
            if idx is None or idx < 3:
                continue

            prior_3 = strategy.bars[idx-3:idx]
            if e["direction"] == "BULL":
                same_dir = sum(1 for b in prior_3 if b.is_bullish)
            else:
                same_dir = sum(1 for b in prior_3 if b.is_bearish)

            if same_dir >= 2:
                with_momentum.append(e)
            else:
                against_momentum.append(e)

        def cont_rate(lst):
            if not lst:
                return 0, 0
            good = [e for e in lst if e["max_favorable"] > e["max_adverse"]]
            return len(good) / len(lst), len(lst)

        r1, n1 = cont_rate(with_momentum)
        r2, n2 = cont_rate(against_momentum)
        print(f"\n  {root}:")
        print(f"    With momentum (2+/3 same dir):    {n1:>4} bars | continuation: {r1:.1%}")
        print(f"    Against momentum (<2/3 same dir): {n2:>4} bars | continuation: {r2:.1%}")


if __name__ == "__main__":
    main()
