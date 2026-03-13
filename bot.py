#!/usr/bin/env python3
"""
Alpaca Elephant-Bar Trading Bot
================================
Trades the first 20 minutes of the session (9:30–9:50 AM ET) using
the Elephant Bar candlestick pattern on 1-minute bars.

Usage
-----
    # paper mode (default)
    ALPACA_API_KEY=... ALPACA_SECRET_KEY=... python bot.py

    # live mode
    ALPACA_PAPER=false ALPACA_API_KEY=... ALPACA_SECRET_KEY=... python bot.py
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from config.settings import (
    HISTORICAL_BARS_DAYS,
    MAX_DAILY_LOSS_PCT,
    MAX_POSITIONS,
    MAX_RISK_PER_TRADE_PCT,
    PAPER_MODE,
    TRADE_LOG_PATH,
    TRADING_END_HOUR,
    TRADING_END_MINUTE,
    TRADING_START_HOUR,
    TRADING_START_MINUTE,
    TRADING_WINDOW_MINUTES,
    WATCHLIST,
)
from src.data.broker import Broker
from src.data.screener import check_market_condition, screen_stocks
from src.strategy.elephant_bar import Signal, detect_elephant_bar
from src.utils.notifications import notify
from src.utils.trade_log import log_trade

# ── Logging ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-9s %(name)s — %(message)s",
)
log = logging.getLogger("bot")

ET = ZoneInfo("America/New_York")


class TradingBot:
    """Orchestrates the full trading session lifecycle."""

    def __init__(self) -> None:
        self.broker = Broker()
        self.bar_buffers: dict[str, pd.DataFrame] = {}
        self.active_signals: dict[str, Signal] = {}
        self.session_pnl: float = 0.0
        self.trade_count: int = 0
        self.starting_equity: float = 0.0
        self._running = True
        self._window_end: datetime | None = None

    # ── Account display ─────────────────────────────────────────────

    def print_account(self) -> None:
        acct = self.broker.get_account()
        mode = "📄 PAPER" if PAPER_MODE else "💰 LIVE"
        print(
            "\n" + "=" * 50 + "\n"
            f"ALPACA ACCOUNT  {mode}\n"
            f"  Equity:         $ {float(acct.equity):>12,.2f}\n"
            f"  Buying Power:   $ {float(acct.buying_power):>12,.2f}\n"
            f"  Cash:           $ {float(acct.cash):>12,.2f}\n"
            f"  Status:          {acct.status}\n"
            f"  PDT Flag:        {'❌ Yes' if acct.pattern_day_trader else '✅ No'}\n"
            f"  Day Trades Used: {acct.daytrade_count}/3\n"
            + "=" * 50
        )
        self.starting_equity = float(acct.equity)

    # ── Pre-market ──────────────────────────────────────────────────

    def run_screener(self) -> list[str]:
        """Run the pre-market screener and return valid tickers."""
        log.info("Running pre-market screener...")
        market = check_market_condition(self.broker)

        candidates = screen_stocks(self.broker, WATCHLIST)

        if candidates:
            log.info("Screener passed: %s", ", ".join(candidates))
        else:
            log.info("Screener done — falling back to full watchlist.")

        return candidates if candidates else list(WATCHLIST)

    def warmup_indicators(self, symbols: list[str]) -> None:
        """Pre-load daily bars so MA200 is ready from bar 1."""
        log.info("Pre-loading historical bars to warm up indicators...")
        for symbol in symbols:
            try:
                df = self.broker.get_daily_bars(symbol, days=HISTORICAL_BARS_DAYS)
                self.bar_buffers[symbol] = df
                ma_status = "ready" if len(df) >= 200 else f"only {len(df)} bars"
                log.info("  %s: loaded %d bars, MA200=%s", symbol, len(df), ma_status)
            except Exception as exc:
                log.warning("  %s: warmup failed — %s", symbol, exc)
                self.bar_buffers[symbol] = pd.DataFrame()

    # ── Real-time bar handling ──────────────────────────────────────

    async def on_bar(self, bar) -> None:
        """Callback for each incoming 1-minute bar."""
        symbol = bar.symbol
        now_et = datetime.now(ET)

        # Enforce trading window
        if self._window_end and now_et >= self._window_end:
            return

        # Append bar to buffer
        new_row = pd.DataFrame(
            [{
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
            }],
            index=[bar.timestamp],
        )

        if symbol in self.bar_buffers and not self.bar_buffers[symbol].empty:
            self.bar_buffers[symbol] = pd.concat(
                [self.bar_buffers[symbol], new_row]
            )
        else:
            self.bar_buffers[symbol] = new_row

        # Check daily loss limit
        if self.starting_equity > 0:
            loss_pct = (self.session_pnl / self.starting_equity) * 100
            if loss_pct <= -MAX_DAILY_LOSS_PCT:
                log.warning("Daily loss limit hit (%.2f%%). Skipping signals.", loss_pct)
                return

        # Already in this position?
        if symbol in self.active_signals:
            self._manage_position(symbol, float(bar.close))
            return

        # Max positions check
        if len(self.active_signals) >= MAX_POSITIONS:
            return

        # ── Detect elephant bar ─────────────────────────────────────
        sig = detect_elephant_bar(self.bar_buffers[symbol], symbol)
        if sig is not None:
            self._enter_trade(sig)

    def _enter_trade(self, sig: Signal) -> None:
        """Execute an entry based on a signal."""
        acct = self.broker.get_account()
        equity = float(acct.equity)
        risk_amount = equity * (MAX_RISK_PER_TRADE_PCT / 100)
        risk_per_share = abs(sig.entry_price - sig.stop_loss)

        if risk_per_share <= 0:
            return

        qty = int(risk_amount / risk_per_share)
        if qty <= 0:
            return

        side = "buy" if sig.direction.value == "long" else "sell"

        try:
            self.broker.submit_market_order(sig.symbol, qty, side)
            self.active_signals[sig.symbol] = sig
            self.trade_count += 1

            msg = (
                f"🔔 **ENTRY** {side.upper()} {sig.symbol}\n"
                f"Qty: `{qty}` @ `${sig.entry_price:.2f}`\n"
                f"SL: `${sig.stop_loss:.2f}` | TP: `${sig.target:.2f}`"
            )
            notify(msg)

            log_trade(sig.symbol, side, qty, sig.entry_price, reason="elephant_bar")

        except Exception as exc:
            log.error("Order failed for %s: %s", sig.symbol, exc)

    def _manage_position(self, symbol: str, current_price: float) -> None:
        """Check stop-loss and take-profit on open positions."""
        sig = self.active_signals[symbol]

        hit_stop = False
        hit_target = False

        if sig.direction.value == "long":
            hit_stop = current_price <= sig.stop_loss
            hit_target = current_price >= sig.target
        else:
            hit_stop = current_price >= sig.stop_loss
            hit_target = current_price <= sig.target

        if hit_stop or hit_target:
            reason = "stop_loss" if hit_stop else "take_profit"
            pnl_per_share = (
                (current_price - sig.entry_price)
                if sig.direction.value == "long"
                else (sig.entry_price - current_price)
            )

            try:
                self.broker.close_position(symbol)
            except Exception as exc:
                log.error("Failed to close %s: %s", symbol, exc)
                return

            del self.active_signals[symbol]
            self.session_pnl += pnl_per_share  # simplified

            emoji = "✅" if pnl_per_share > 0 else "❌"
            msg = (
                f"{emoji} **EXIT** {symbol} ({reason})\n"
                f"PnL/share: `${pnl_per_share:+.2f}`"
            )
            notify(msg)
            log_trade(
                symbol, "close", 0, sig.entry_price,
                exit_price=current_price,
                pnl=pnl_per_share,
                reason=reason,
            )

    # ── Session lifecycle ───────────────────────────────────────────

    def _compute_window_end(self) -> datetime:
        """Compute the session end time.

        If started before or at 9:30, the window ends at 9:50.
        If started late (after 9:30), the window is the *later* of
        the normal 9:50 cutoff or now + TRADING_WINDOW_MINUTES, capped at 4 PM.
        """
        now = datetime.now(ET)
        normal_end = now.replace(
            hour=TRADING_END_HOUR,
            minute=TRADING_END_MINUTE,
            second=0,
            microsecond=0,
        )
        market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        late_end = now + timedelta(minutes=TRADING_WINDOW_MINUTES)

        # Use whichever is later (normal window vs late-start window),
        # but never past market close.
        end = max(normal_end, late_end)
        return min(end, market_close)

    async def wait_for_market_open(self) -> None:
        """Sleep until 9:30 AM ET."""
        now = datetime.now(ET)
        market_open = now.replace(
            hour=TRADING_START_HOUR,
            minute=TRADING_START_MINUTE,
            second=0,
            microsecond=0,
        )

        if now >= market_open:
            return

        wait_secs = (market_open - now).total_seconds()
        if wait_secs > 0:
            log.info(
                "Screener done. Market opens in %ds. Waiting...",
                int(wait_secs),
            )
            await asyncio.sleep(wait_secs)

    async def run_session(self, symbols: list[str]) -> None:
        """Run the trading session."""
        acct = self.broker.get_account()
        balance = float(acct.equity)

        tickers_str = ", ".join(symbols)
        mode = "PAPER" if PAPER_MODE else "LIVE"

        window_end = self._compute_window_end()
        self._window_end = window_end
        end_str = window_end.strftime("%-I:%M %p ET")

        log.info(
            "Session started | Balance: $%s | Tickers: %s | Mode: %s",
            f"{balance:,.2f}", tickers_str, mode,
        )
        log.info("Trading window ends at %s", end_str)

        notify(
            f"🔔 **{'📄 PAPER' if PAPER_MODE else '💰 LIVE'} SESSION STARTED**\n"
            f"Balance:   `${balance:,.2f}`\n"
            f"Watching:  `{tickers_str}`\n"
            f"Window:    `9:30 – {end_str}`"
        )

        # Warm up minute-level buffers with historical bars
        self.warmup_indicators(symbols)

        # Start streaming
        stream_task = asyncio.create_task(
            self.broker.stream_bars(symbols, self.on_bar)
        )

        # Wait until window end
        now = datetime.now(ET)
        remaining = (window_end - now).total_seconds()
        if remaining > 0:
            log.info("Streaming live bars for %d minutes...", int(remaining / 60))
            await asyncio.sleep(remaining)

        log.info("Trading window closed (9:50 AM timeout).")
        log.info("Trading window reached 9:50 AM — evaluating open positions...")

        # Close any remaining positions
        for symbol in list(self.active_signals.keys()):
            try:
                self.broker.close_position(symbol)
                del self.active_signals[symbol]
            except Exception as exc:
                log.warning("Could not close %s: %s", symbol, exc)

        # Stop stream
        await self.broker.stop_stream()
        stream_task.cancel()
        try:
            await stream_task
        except asyncio.CancelledError:
            pass

        # Session summary
        pnl_pct = (
            (self.session_pnl / self.starting_equity * 100)
            if self.starting_equity
            else 0
        )
        final_balance = float(self.broker.get_account().equity)

        log.info(
            "Session complete | PnL: $%+.2f (%.2f%%) | Trades: %d | Balance: $%s",
            self.session_pnl, pnl_pct, self.trade_count, f"{final_balance:,.2f}",
        )

        notify(
            f"📈 **{'📄 PAPER' if PAPER_MODE else '💰 LIVE'} SESSION COMPLETE**\n"
            f"Daily PnL: `${self.session_pnl:+,.2f}`\n"
            f"Trades:    `{self.trade_count}`\n"
            f"Balance:   `${final_balance:,.2f}`"
        )

        print(
            f"\n{'=' * 55}\n"
            f"SESSION COMPLETE  |  {mode}\n"
            f"  Daily PnL:   $ {self.session_pnl:>+12,.2f}  ({pnl_pct:.2f}%)\n"
            f"  Balance:     $ {final_balance:>12,.2f}\n"
            f"  Trades:       {self.trade_count}\n"
            f"  Trade log:    {TRADE_LOG_PATH}\n"
            f"{'=' * 55}"
        )

        log.info("Session complete. Sleeping until next market open...")


async def main() -> None:
    bot = TradingBot()

    mode = "PAPER" if PAPER_MODE else "LIVE"
    log.info("Bot started. Running in %s mode.", mode)

    bot.print_account()

    # Pre-market screener
    symbols = bot.run_screener()

    # Wait for market open
    await bot.wait_for_market_open()

    # Run the session
    await bot.run_session(symbols)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Bot interrupted by user.")
        sys.exit(0)
