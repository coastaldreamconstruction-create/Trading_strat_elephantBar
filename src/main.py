"""
Elephant Bar Breakout Strategy — Main Bot Runner
Orchestrates strategy instances across all configured contracts.

Usage:
    python -m src.main                  # Run 2-min mode (default)
    python -m src.main --mode 1hr       # Run 1-hour mode (longs only, 4 contracts)
    python -m src.main --dry-run        # Log signals but don't place orders
"""
import argparse
import logging
import time
import sys
from datetime import datetime, timezone

from src import config
from src.strategy import ElephantBarStrategy, Bar, Signal
from src.broker import WebullBroker, get_front_month_symbol, aggregate_to_2min


# ─────────────────────────────────────────────
# Logging setup
# ─────────────────────────────────────────────
def setup_logging(level: str = config.LOG_LEVEL):
    fmt = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.LOG_FILE),
        ],
    )


logger = logging.getLogger("main")


# ─────────────────────────────────────────────
# Trade Manager
# ─────────────────────────────────────────────
class TradeManager:
    """Tracks active orders and P&L across all contracts."""

    def __init__(self):
        self.pending_entries: dict[str, str] = {}   # symbol -> client_order_id
        self.active_stops: dict[str, str] = {}      # symbol -> client_order_id
        self.daily_pnl: float = 0.0
        self.trade_count: int = 0

    def record_pnl(self, pnl: float):
        self.daily_pnl += pnl
        self.trade_count += 1

    @property
    def kill_switch_triggered(self) -> bool:
        return self.daily_pnl <= -config.MAX_DAILY_LOSS


# ─────────────────────────────────────────────
# Bot Engine
# ─────────────────────────────────────────────
class ElephantBarBot:
    """
    Main bot that:
    1. Initializes a strategy instance per contract
    2. Polls bars on a timer
    3. Routes signals to the broker
    4. Manages stops and exits
    """

    def __init__(self, mode: str = "2min", dry_run: bool = False):
        self.mode = mode
        self.dry_run = dry_run
        self.broker = WebullBroker()
        self.manager = TradeManager()
        self.strategies: dict[str, ElephantBarStrategy] = {}
        self.symbols: dict[str, str] = {}  # root -> full symbol (e.g., MES -> MESH6)
        self.last_bar_ts: dict[str, float] = {}

        if mode == "1hr":
            self.contracts = config.CONTRACTS_1HR
            self.allow_shorts = config.ENABLE_SHORTS_1HR
            self.poll_seconds = 3600
            self.bar_timespan = "H1"
            self.aggregate_2min = False
        else:
            self.contracts = config.CONTRACTS_2MIN
            self.allow_shorts = config.ENABLE_SHORTS_2MIN
            self.poll_seconds = config.BAR_INTERVAL_SECONDS
            self.bar_timespan = "M1"
            self.aggregate_2min = True

    def initialize(self) -> bool:
        """Connect to broker and set up strategy instances."""
        if not self.dry_run:
            if not self.broker.connect():
                logger.error("Failed to connect to Webull. Exiting.")
                return False
            balance = self.broker.get_account_balance()
            if balance:
                logger.info("Account balance: %s", balance)
            else:
                logger.warning("Could not fetch account balance — continuing anyway.")

        ref_date = datetime.now(timezone.utc)
        for root, spec in self.contracts.items():
            full_symbol = get_front_month_symbol(root, ref_date)
            self.symbols[root] = full_symbol
            self.last_bar_ts[root] = 0
            self.strategies[root] = ElephantBarStrategy(
                symbol=full_symbol,
                tick_size=spec["tick_size"],
                allow_shorts=self.allow_shorts,
            )
            logger.info(
                "Initialized %s -> %s (tick=%.4f, value=$%.2f)",
                root, full_symbol, spec["tick_size"], spec["tick_value"],
            )

        logger.info(
            "Bot ready: mode=%s, contracts=%d, dry_run=%s, poll=%ds",
            self.mode, len(self.contracts), self.dry_run, self.poll_seconds,
        )
        return True

    def warm_up(self):
        """Load historical bars to warm up SMA/ATR indicators."""
        logger.info("Warming up indicators with historical data...")
        for root, strat in self.strategies.items():
            symbol = self.symbols[root]
            if self.dry_run:
                logger.info("  [DRY RUN] Skipping warm-up for %s", symbol)
                continue

            fetch_count = 450 if self.aggregate_2min else 210
            raw_bars = self.broker.get_historical_bars(
                symbol, timespan=self.bar_timespan, count=fetch_count
            )
            if not raw_bars:
                logger.warning("  No historical data for %s — strategy will lag.", root)
                continue

            if self.aggregate_2min:
                bars = aggregate_to_2min(raw_bars)
            else:
                bars = raw_bars

            for bar_dict in bars:
                bar = Bar(
                    timestamp=bar_dict["timestamp"],
                    open=bar_dict["open"],
                    high=bar_dict["high"],
                    low=bar_dict["low"],
                    close=bar_dict["close"],
                    volume=bar_dict["volume"],
                )
                strat.on_bar(bar)

            if bars:
                self.last_bar_ts[root] = bars[-1]["timestamp"]
            logger.info(
                "  %s: loaded %d bars, strategy has %d bars buffered",
                root, len(bars), len(strat.bars),
            )

    def poll_and_process(self):
        """Fetch latest bars for all contracts, run strategy, handle signals."""
        for root, strat in self.strategies.items():
            symbol = self.symbols[root]

            if self.manager.kill_switch_triggered:
                logger.critical(
                    "KILL SWITCH: Daily loss $%.2f exceeds limit. Halting.",
                    self.manager.daily_pnl,
                )
                return False

            if self.manager.trade_count >= config.MAX_OPEN_TRADES and not strat.is_in_trade:
                logger.debug("Max open trades reached, skipping %s", root)
                continue

            if self.dry_run:
                continue

            raw_bars = self.broker.get_historical_bars(
                symbol, timespan=self.bar_timespan, count=5
            )
            if not raw_bars:
                continue

            if self.aggregate_2min:
                bars = aggregate_to_2min(raw_bars)
            else:
                bars = raw_bars

            new_bars = [
                b for b in bars if b["timestamp"] > self.last_bar_ts.get(root, 0)
            ]
            for bar_dict in new_bars:
                bar = Bar(
                    timestamp=bar_dict["timestamp"],
                    open=bar_dict["open"],
                    high=bar_dict["high"],
                    low=bar_dict["low"],
                    close=bar_dict["close"],
                    volume=bar_dict["volume"],
                )
                signals = strat.on_bar(bar)
                self.last_bar_ts[root] = bar_dict["timestamp"]
                for signal in signals:
                    self._handle_signal(root, signal)
        return True

    def _handle_signal(self, root: str, signal: Signal):
        """Route a strategy signal to the appropriate broker action."""
        if signal.signal_type == "ENTRY":
            logger.info(
                ">>> ENTRY SIGNAL: %s %s @ %.4f | stop=%.4f",
                signal.direction, signal.symbol, signal.entry_price, signal.stop_price,
            )
            if self.dry_run:
                logger.info("  [DRY RUN] Would place limit order.")
                return

            side = "BUY" if signal.direction == "LONG" else "SELL"
            order_id = self.broker.place_limit_order(
                signal.symbol, side=side, price=signal.entry_price,
                qty=config.POSITION_SIZE,
            )
            if order_id:
                self.manager.pending_entries[root] = order_id
                stop_side = "SELL" if signal.direction == "LONG" else "BUY"
                stop_id = self.broker.place_stop_order(
                    signal.symbol, side=stop_side, stop_price=signal.stop_price,
                    qty=config.POSITION_SIZE,
                )
                if stop_id:
                    self.manager.active_stops[root] = stop_id
                self.strategies[root].register_fill(signal)

        elif signal.signal_type in ("PUSH_EXIT", "STOP_EXIT"):
            logger.info(
                ">>> EXIT SIGNAL (%s): %s %s @ %.4f",
                signal.signal_type, signal.direction, signal.symbol,
                signal.entry_price,
            )
            if self.dry_run:
                logger.info("  [DRY RUN] Would place market exit.")
                return

            if root in self.manager.active_stops:
                self.broker.cancel_order(self.manager.active_stops[root])
                del self.manager.active_stops[root]

            exit_side = "SELL" if signal.direction == "LONG" else "BUY"
            self.broker.place_market_order(
                signal.symbol, side=exit_side, qty=config.POSITION_SIZE,
            )
            self.manager.pending_entries.pop(root, None)
            self.strategies[root].close_trade()

    def run(self):
        """Main event loop."""
        logger.info("=" * 60)
        logger.info("Elephant Bar Breakout Bot — Starting")
        logger.info("  Mode: %s | Dry Run: %s", self.mode, self.dry_run)
        logger.info("  Contracts: %s", list(self.contracts.keys()))
        logger.info("=" * 60)

        if not self.initialize():
            return

        self.warm_up()
        logger.info("Entering main loop (poll every %ds)...", self.poll_seconds)

        try:
            while True:
                loop_start = time.time()
                alive = self.poll_and_process()
                if not alive:
                    logger.critical("Bot shutting down due to kill switch.")
                    break
                elapsed = time.time() - loop_start
                sleep_time = max(0, self.poll_seconds - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)
        except KeyboardInterrupt:
            logger.info("Interrupted by user. Shutting down gracefully...")
        except Exception as e:
            logger.exception("Unhandled error: %s", e)
        finally:
            self._shutdown()

    def _shutdown(self):
        """Clean shutdown — log final state."""
        logger.info("─" * 40)
        logger.info("Session Summary:")
        logger.info("  Daily P&L: $%.2f", self.manager.daily_pnl)
        logger.info("  Trades: %d", self.manager.trade_count)
        for root, strat in self.strategies.items():
            status = "IN TRADE" if strat.is_in_trade else "FLAT"
            logger.info("  %s: %s", root, status)
        logger.info("─" * 40)
        logger.info("Bot stopped.")


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Elephant Bar Breakout Bot")
    parser.add_argument(
        "--mode", choices=["2min", "1hr"], default="2min",
        help="Timeframe mode (default: 2min)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Log signals without placing real orders",
    )
    args = parser.parse_args()

    setup_logging()
    bot = ElephantBarBot(mode=args.mode, dry_run=args.dry_run)
    bot.run()


if __name__ == "__main__":
    main()
