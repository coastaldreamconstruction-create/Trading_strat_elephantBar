#!/usr/bin/env python3
"""
Analyze where Best Combo B loses money to find filterable patterns.
122 losses at ~$33 each = ~$4,069 leaked. Can we cut some of those?
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.run_backtest import load_bars_from_csv
from src.strategy.core import Bar, ElephantBarStrategy
from src.backtest.engine import Backtester, BacktestResult
from src import config

CONTRACTS = ["MES", "MNQ", "MYM", "MCL", "MGC", "MSI"]
BEST_COMBO_B = {
    "require_counter_momentum": True,
    "elephant_mult": 2.5,
    "push_exit_count": 8,
}


def find_csv(root):
    for f in sorted(os.listdir("data"), reverse=True):
        if f.startswith(root + "_") and "2min" in f and f.endswith(".csv"):
            return os.path.join("data", f)
    return ""


def section(title):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def main():
    all_trades = []
    all_bars_by_symbol = {}

    for root in CONTRACTS:
        csv_path = find_csv(root)
        if not csv_path:
            continue
        bars = load_bars_from_csv(csv_path)
        all_bars_by_symbol[root] = bars
        spec = config.CONTRACTS_2MIN[root]

        bt = Backtester(
            symbol=root,
            tick_size=spec["tick_size"],
            tick_value=spec["tick_value"],
            allow_shorts=True,
            starting_capital=config.STARTING_CAPITAL,
            max_daily_loss=config.MAX_DAILY_LOSS,
            **BEST_COMBO_B,
        )
        result = bt.run(bars)
        all_trades.extend(result.trades)

    winners = [t for t in all_trades if t.pnl > 0]
    losers = [t for t in all_trades if t.pnl <= 0]

    print(f"Total: {len(all_trades)} trades | {len(winners)} wins | {len(losers)} losses")
    print(f"Total P&L: ${sum(t.pnl for t in all_trades):,.2f}")

    # ══════════════════════════════════════════════
    # 1. TIME OF DAY — When do losses cluster?
    # ══════════════════════════════════════════════
    section("1. LOSSES BY TIME OF DAY (UTC)")
    sessions = {
        "Asia (00-08)": range(0, 8),
        "London (08-14)": range(8, 14),
        "US RTH (14-21)": range(14, 21),
        "Evening (21-00)": range(21, 24),
    }

    for session_name, hours in sessions.items():
        session_w = [t for t in winners if _hour(t.entry_timestamp) in hours]
        session_l = [t for t in losers if _hour(t.entry_timestamp) in hours]
        total = len(session_w) + len(session_l)
        pnl = sum(t.pnl for t in session_w) + sum(t.pnl for t in session_l)
        wr = len(session_w) / total if total > 0 else 0
        print(f"  {session_name:<20} {total:>3} trades | {len(session_w):>2}W {len(session_l):>3}L | WR: {wr:.0%} | P&L: ${pnl:>8,.2f}")

    # ══════════════════════════════════════════════
    # 2. DAY OF WEEK
    # ══════════════════════════════════════════════
    section("2. LOSSES BY DAY OF WEEK")
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for dow in range(7):
        day_w = [t for t in winners if _dow(t.entry_timestamp) == dow]
        day_l = [t for t in losers if _dow(t.entry_timestamp) == dow]
        total = len(day_w) + len(day_l)
        if total == 0:
            continue
        pnl = sum(t.pnl for t in day_w) + sum(t.pnl for t in day_l)
        wr = len(day_w) / total if total > 0 else 0
        print(f"  {days[dow]:<10} {total:>3} trades | {len(day_w):>2}W {len(day_l):>3}L | WR: {wr:.0%} | P&L: ${pnl:>8,.2f}")

    # ══════════════════════════════════════════════
    # 3. STOP DISTANCE — Are wide stops bleeding more?
    # ══════════════════════════════════════════════
    section("3. STOP DISTANCE ANALYSIS")
    for label, trades in [("Winners", winners), ("Losers", losers)]:
        if not trades:
            continue
        stop_dists = [abs(t.entry_price - t.stop_price) for t in trades]
        avg_stop = sum(stop_dists) / len(stop_dists)
        min_stop = min(stop_dists)
        max_stop = max(stop_dists)
        print(f"  {label:<10} avg stop dist: {avg_stop:.4f} | min: {min_stop:.4f} | max: {max_stop:.4f}")

    # Check if capping stop distance helps
    section("4. WHAT IF WE CAP STOP DISTANCE? (skip trades with wide stops)")
    # Compute stop in ATR multiples - use raw price distance as proxy
    for label, trades in [("All trades", all_trades)]:
        stop_dists = sorted([abs(t.entry_price - t.stop_price) / t.tick_size for t in trades])
        median_ticks = stop_dists[len(stop_dists) // 2]
        print(f"  Median stop distance: {median_ticks:.0f} ticks")
        print(f"  25th percentile: {stop_dists[len(stop_dists) // 4]:.0f} ticks")
        print(f"  75th percentile: {stop_dists[3 * len(stop_dists) // 4]:.0f} ticks")

    # Simulate filtering by max stop distance in ticks
    print(f"\n  Filtering by max stop distance (ticks):")
    for max_ticks in [20, 30, 40, 50, 75, 100, 150, 200]:
        filtered = [t for t in all_trades
                    if abs(t.entry_price - t.stop_price) / t.tick_size <= max_ticks]
        if not filtered:
            continue
        f_pnl = sum(t.pnl for t in filtered)
        f_wins = sum(1 for t in filtered if t.pnl > 0)
        f_wr = f_wins / len(filtered)
        print(f"    <= {max_ticks:>3} ticks: {len(filtered):>3} trades | WR: {f_wr:.0%} | P&L: ${f_pnl:>8,.2f}")

    # ══════════════════════════════════════════════
    # 5. DIRECTION ANALYSIS
    # ══════════════════════════════════════════════
    section("5. DIRECTION — LONGS vs SHORTS")
    for direction in ["LONG", "SHORT"]:
        dir_trades = [t for t in all_trades if t.direction == direction]
        if not dir_trades:
            continue
        dir_w = [t for t in dir_trades if t.pnl > 0]
        pnl = sum(t.pnl for t in dir_trades)
        wr = len(dir_w) / len(dir_trades)
        print(f"  {direction:<6} {len(dir_trades):>3} trades | {len(dir_w):>2}W | WR: {wr:.0%} | P&L: ${pnl:>8,.2f}")

    # Per contract direction
    print(f"\n  Per-contract direction:")
    for root in CONTRACTS:
        for direction in ["LONG", "SHORT"]:
            ct = [t for t in all_trades if t.symbol == root and t.direction == direction]
            if not ct:
                continue
            w = sum(1 for t in ct if t.pnl > 0)
            pnl = sum(t.pnl for t in ct)
            wr = w / len(ct) if ct else 0
            print(f"    {root} {direction:<6} {len(ct):>3} trades | {w:>2}W | WR: {wr:.0%} | P&L: ${pnl:>8,.2f}")

    # ══════════════════════════════════════════════
    # 6. CONSECUTIVE LOSSES — Streaks
    # ══════════════════════════════════════════════
    section("6. LOSS STREAKS")
    streak = 0
    max_streak = 0
    streaks = []
    for t in all_trades:
        if t.pnl <= 0:
            streak += 1
        else:
            if streak > 0:
                streaks.append(streak)
            streak = 0
        max_streak = max(max_streak, streak)
    if streak > 0:
        streaks.append(streak)
    avg_streak = sum(streaks) / len(streaks) if streaks else 0
    print(f"  Max loss streak: {max_streak}")
    print(f"  Avg loss streak: {avg_streak:.1f}")
    print(f"  Streak distribution: {sorted(streaks, reverse=True)[:10]}")

    # ══════════════════════════════════════════════
    # 7. EXIT REASON BREAKDOWN
    # ══════════════════════════════════════════════
    section("7. EXIT REASON BREAKDOWN")
    for reason in ["STOP_EXIT", "PUSH_EXIT"]:
        reason_trades = [t for t in all_trades if t.exit_reason == reason]
        if not reason_trades:
            continue
        pnl = sum(t.pnl for t in reason_trades)
        w = sum(1 for t in reason_trades if t.pnl > 0)
        wr = w / len(reason_trades)
        avg_pnl = pnl / len(reason_trades)
        print(f"  {reason:<12} {len(reason_trades):>3} trades | {w:>2}W | WR: {wr:.0%} | P&L: ${pnl:>8,.2f} | Avg: ${avg_pnl:>7,.2f}")

    # ══════════════════════════════════════════════
    # 8. TRADE DURATION
    # ══════════════════════════════════════════════
    section("8. TRADE DURATION (bars)")
    for label, trades in [("Winners", winners), ("Losers", losers)]:
        if not trades:
            continue
        durations = [(t.exit_timestamp - t.entry_timestamp) / 120 for t in trades]  # 2-min bars
        avg_dur = sum(durations) / len(durations)
        min_dur = min(durations)
        max_dur = max(durations)
        print(f"  {label:<10} avg: {avg_dur:.0f} bars | min: {min_dur:.0f} | max: {max_dur:.0f}")


def _hour(ts):
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).hour
    except Exception:
        return -1


def _dow(ts):
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).weekday()
    except Exception:
        return -1


if __name__ == "__main__":
    main()
