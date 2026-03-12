#!/usr/bin/env python3
"""
Diagnostic script — checks how often each entry condition is met
to find which filter is too restrictive.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.strategy.core import Bar, ElephantBarStrategy
from scripts.run_backtest import load_bars_from_csv
from src import config


def diagnose(csv_path: str):
    bars = load_bars_from_csv(csv_path)
    print(f"Loaded {len(bars)} bars\n")

    strat = ElephantBarStrategy(
        symbol="MES",
        tick_size=0.25,
        allow_shorts=True,
    )

    total = 0
    narrow_count = 0
    elephant_count = 0
    no_tail_count = 0
    narrow_and_elephant = 0
    narrow_and_tail = 0
    elephant_and_tail = 0
    all_three = 0

    for bar in bars:
        strat.bars.append(bar)

        if len(strat.bars) < config.SMA_SLOW + 1:
            continue

        total += 1
        sma_fast = strat._sma(config.SMA_FAST)
        sma_slow = strat._sma(config.SMA_SLOW)
        atr = strat._atr()
        avg_body = strat._avg_body()

        if any(v is None for v in [sma_fast, sma_slow, atr, avg_body]):
            continue

        narrow = strat._is_narrow(sma_fast, sma_slow, atr)
        elephant = strat._is_elephant(bar, avg_body)
        no_tail = bar.is_no_tail

        if narrow:
            narrow_count += 1
        if elephant:
            elephant_count += 1
        if no_tail:
            no_tail_count += 1
        if narrow and elephant:
            narrow_and_elephant += 1
        if narrow and no_tail:
            narrow_and_tail += 1
        if elephant and no_tail:
            elephant_and_tail += 1
        if narrow and elephant and no_tail:
            all_three += 1

            # Print details of qualifying bars
            gap = abs(sma_fast - sma_slow)
            ratio = bar.body / avg_body if avg_body else 0
            body_pct = (bar.body / bar.full_range * 100) if bar.full_range else 0
            direction = "BULL" if bar.is_bullish else "BEAR" if bar.is_bearish else "DOJI"
            print(
                f"  MATCH: ts={bar.timestamp:.0f} {direction} "
                f"O={bar.open:.2f} H={bar.high:.2f} L={bar.low:.2f} C={bar.close:.2f} "
                f"body={bar.body:.2f} avg={avg_body:.2f} ratio={ratio:.1f}x "
                f"gap={gap:.2f} atr={atr:.2f} body%={body_pct:.0f}%"
            )

    print(f"\n{'='*60}")
    print(f"Bars analyzed (after warmup): {total}")
    print(f"{'='*60}")
    print(f"  Narrow SMAs (gap <= {config.NARROW_THRESHOLD} x ATR):  {narrow_count} ({narrow_count/total*100:.1f}%)")
    print(f"  Elephant bar (body >= {config.ELEPHANT_MULT}x avg):     {elephant_count} ({elephant_count/total*100:.1f}%)")
    print(f"  No tail (body >= 90% of range):       {no_tail_count} ({no_tail_count/total*100:.1f}%)")
    print(f"  Narrow + Elephant:                     {narrow_and_elephant} ({narrow_and_elephant/total*100:.2f}%)")
    print(f"  Narrow + No tail:                      {narrow_and_tail} ({narrow_and_tail/total*100:.2f}%)")
    print(f"  Elephant + No tail:                    {elephant_and_tail} ({elephant_and_tail/total*100:.2f}%)")
    print(f"  ALL THREE (signal candidates):         {all_three} ({all_three/total*100:.2f}%)")
    print(f"{'='*60}")

    if all_three == 0:
        print("\nNo bars passed all 3 filters. Suggestions:")
        if narrow_count == 0:
            print("  -> NARROW is the blocker. Try increasing NARROW_THRESHOLD (currently 1.0)")
        elif elephant_count == 0:
            print("  -> ELEPHANT is the blocker. Try decreasing ELEPHANT_MULT (currently 2.0)")
        elif no_tail_count < total * 0.01:
            print("  -> NO_TAIL is very rare. The 90% body-to-range filter is very strict on 2-min bars.")
        else:
            print("  -> Each condition passes individually but they rarely overlap.")
            print("  -> Try relaxing NARROW_THRESHOLD or ELEPHANT_MULT slightly.")


if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "data/MES_2min_2025-12-12_to_2026-03-12.csv"
    diagnose(csv_path)
