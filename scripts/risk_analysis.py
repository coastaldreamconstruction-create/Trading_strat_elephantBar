#!/usr/bin/env python3
"""Detailed risk analysis for Best Combo B variant."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.run_backtest import load_bars_from_csv
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


def main():
    all_trades = []

    for root in CONTRACTS:
        csv_path = find_csv(root)
        if not csv_path:
            continue
        bars = load_bars_from_csv(csv_path)
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

        print(f"{root}: {result.total_trades} trades, P&L: ${result.total_pnl:,.2f}")

    print(f"\n{'=' * 60}")
    print(f"  BEST COMBO B — RISK ANALYSIS")
    print(f"{'=' * 60}")

    # Total risk per trade = |entry - stop| * tick_value / tick_size
    total_risked = 0
    for t in all_trades:
        risk_per_trade = abs(t.entry_price - t.stop_price) * t.tick_value / t.tick_size
        total_risked += risk_per_trade

    total_pnl = sum(t.pnl for t in all_trades)
    winners = [t for t in all_trades if t.pnl > 0]
    losers = [t for t in all_trades if t.pnl <= 0]

    avg_risk = total_risked / len(all_trades) if all_trades else 0
    max_single_loss = min(t.pnl for t in all_trades) if all_trades else 0
    max_single_win = max(t.pnl for t in all_trades) if all_trades else 0

    # Drawdown
    equity = config.STARTING_CAPITAL
    peak = equity
    max_dd = 0
    for t in all_trades:
        equity += t.pnl
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    print(f"  Time period:        Jan 30 – Mar 11, 2026 (~40 calendar days)")
    print(f"  Starting capital:   ${config.STARTING_CAPITAL:,.2f}")
    print(f"  Total trades:       {len(all_trades)}")
    print(f"  Winners:            {len(winners)} ({len(winners)/len(all_trades):.1%})")
    print(f"  Losers:             {len(losers)}")
    print(f"")
    print(f"  Total P&L:          ${total_pnl:,.2f}")
    print(f"  Return on capital:  {total_pnl / config.STARTING_CAPITAL:.1%}")
    print(f"")
    print(f"  Total $ risked:     ${total_risked:,.2f} (sum of all stop distances)")
    print(f"  Avg risk/trade:     ${avg_risk:,.2f}")
    print(f"  Return on risk:     {total_pnl / total_risked:.1%}" if total_risked > 0 else "")
    print(f"")
    print(f"  Max single win:     ${max_single_win:,.2f}")
    print(f"  Max single loss:    ${max_single_loss:,.2f}")
    print(f"  Avg winner:         ${sum(t.pnl for t in winners) / len(winners):,.2f}" if winners else "")
    print(f"  Avg loser:          ${sum(t.pnl for t in losers) / len(losers):,.2f}" if losers else "")
    print(f"")
    print(f"  Max drawdown:       ${max_dd:,.2f}")
    print(f"  DD % of capital:    {max_dd / config.STARTING_CAPITAL:.1%}")
    print(f"  Final equity:       ${config.STARTING_CAPITAL + total_pnl:,.2f}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
