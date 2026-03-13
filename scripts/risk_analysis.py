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


def print_stats(label, trades, starting_capital):
    total_pnl = sum(t.pnl for t in trades)
    winners = [t for t in trades if t.pnl > 0]
    losers = [t for t in trades if t.pnl <= 0]

    total_risked = sum(abs(t.entry_price - t.stop_price) * t.tick_value / t.tick_size for t in trades)
    avg_risk = total_risked / len(trades) if trades else 0
    max_single_loss = min(t.pnl for t in trades) if trades else 0
    max_single_win = max(t.pnl for t in trades) if trades else 0

    equity = starting_capital
    peak = equity
    max_dd = 0
    for t in trades:
        equity += t.pnl
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    gross_profit = sum(t.pnl for t in winners)
    gross_loss = sum(t.pnl for t in losers)
    pf = abs(gross_profit / gross_loss) if gross_loss != 0 else float("inf")

    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    print(f"  Time period:        Jan 30 – Mar 11, 2026 (~40 days)")
    print(f"  Starting capital:   ${starting_capital:,.2f}")
    print(f"  Total trades:       {len(trades)}")
    print(f"  Winners:            {len(winners)} ({len(winners)/len(trades):.1%})" if trades else "")
    print(f"  Losers:             {len(losers)}")
    print(f"")
    print(f"  Total P&L:          ${total_pnl:,.2f}")
    print(f"  Profit factor:      {pf:.2f}")
    print(f"  Return on capital:  {total_pnl / starting_capital:.1%}")
    print(f"")
    print(f"  Total $ risked:     ${total_risked:,.2f}")
    print(f"  Avg risk/trade:     ${avg_risk:,.2f}")
    print(f"  Return on risk:     {total_pnl / total_risked:.1%}" if total_risked > 0 else "")
    print(f"")
    print(f"  Max single win:     ${max_single_win:,.2f}")
    print(f"  Max single loss:    ${max_single_loss:,.2f}")
    print(f"  Avg winner:         ${gross_profit / len(winners):,.2f}" if winners else "")
    print(f"  Avg loser:          ${gross_loss / len(losers):,.2f}" if losers else "")
    print(f"")
    print(f"  Max drawdown:       ${max_dd:,.2f}")
    print(f"  DD % of capital:    {max_dd / starting_capital:.1%}")
    print(f"  Final equity:       ${starting_capital + total_pnl:,.2f}")
    print(f"{'=' * 60}")


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

    # Sort by PnL to find the outlier
    all_trades_sorted = sorted(all_trades, key=lambda t: t.pnl, reverse=True)
    biggest = all_trades_sorted[0]
    print(f"Biggest single trade: {biggest.symbol} {biggest.direction} ${biggest.pnl:,.2f}")

    # All trades
    print_stats("BEST COMBO B — ALL TRADES", all_trades, config.STARTING_CAPITAL)

    # Without the biggest winner
    trades_no_outlier = [t for t in all_trades if t is not biggest]
    print_stats("BEST COMBO B — EXCLUDING BIGGEST WINNER", trades_no_outlier, config.STARTING_CAPITAL)


if __name__ == "__main__":
    main()
