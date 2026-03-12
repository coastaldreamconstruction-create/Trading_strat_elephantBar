"""
Elephant Bar Breakout Strategy — Backtesting Engine
Feeds historical bars through the strategy and tracks simulated trades.
No look-ahead bias: only data available up to the current bar is used.
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

from src.strategy import ElephantBarStrategy, Bar, Signal
from src import config

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """A completed (closed) trade for performance tracking."""
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    stop_price: float
    entry_timestamp: float
    exit_timestamp: float
    exit_reason: str  # "PUSH_EXIT" or "STOP_EXIT"
    tick_size: float
    tick_value: float

    @property
    def price_diff(self) -> float:
        if self.direction == "LONG":
            return self.exit_price - self.entry_price
        else:
            return self.entry_price - self.exit_price

    @property
    def ticks_gained(self) -> float:
        if self.tick_size == 0:
            return 0.0
        return self.price_diff / self.tick_size

    @property
    def pnl(self) -> float:
        """Dollar P&L for 1 contract."""
        return self.ticks_gained * self.tick_value

    @property
    def is_winner(self) -> bool:
        return self.pnl > 0


@dataclass
class BacktestResult:
    """Aggregated results from a backtest run."""
    symbol: str
    trades: list[Trade] = field(default_factory=list)
    starting_capital: float = config.STARTING_CAPITAL

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def winners(self) -> list[Trade]:
        return [t for t in self.trades if t.is_winner]

    @property
    def losers(self) -> list[Trade]:
        return [t for t in self.trades if not t.is_winner]

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return len(self.winners) / self.total_trades

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def gross_profit(self) -> float:
        return sum(t.pnl for t in self.winners)

    @property
    def gross_loss(self) -> float:
        return sum(t.pnl for t in self.losers)

    @property
    def profit_factor(self) -> float:
        if self.gross_loss == 0:
            return float("inf") if self.gross_profit > 0 else 0.0
        return abs(self.gross_profit / self.gross_loss)

    @property
    def avg_winner(self) -> float:
        if not self.winners:
            return 0.0
        return self.gross_profit / len(self.winners)

    @property
    def avg_loser(self) -> float:
        if not self.losers:
            return 0.0
        return self.gross_loss / len(self.losers)

    @property
    def max_drawdown(self) -> float:
        """Maximum peak-to-trough drawdown in dollar terms."""
        if not self.trades:
            return 0.0
        equity = self.starting_capital
        peak = equity
        max_dd = 0.0
        for trade in self.trades:
            equity += trade.pnl
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @property
    def equity_curve(self) -> list[float]:
        """Running equity after each trade."""
        curve = [self.starting_capital]
        for trade in self.trades:
            curve.append(curve[-1] + trade.pnl)
        return curve

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            f"{'─' * 50}",
            f"Backtest Results: {self.symbol}",
            f"{'─' * 50}",
            f"  Total trades:   {self.total_trades}",
            f"  Winners:        {len(self.winners)} ({self.win_rate:.1%})",
            f"  Losers:         {len(self.losers)}",
            f"  Total P&L:      ${self.total_pnl:,.2f}",
            f"  Gross profit:   ${self.gross_profit:,.2f}",
            f"  Gross loss:     ${self.gross_loss:,.2f}",
            f"  Profit factor:  {self.profit_factor:.2f}",
            f"  Avg winner:     ${self.avg_winner:,.2f}",
            f"  Avg loser:      ${self.avg_loser:,.2f}",
            f"  Max drawdown:   ${self.max_drawdown:,.2f}",
            f"  Final equity:   ${self.starting_capital + self.total_pnl:,.2f}",
            f"{'─' * 50}",
        ]
        return "\n".join(lines)


class Backtester:
    """
    Runs the ElephantBarStrategy over a list of historical bars.

    Usage:
        bars = [Bar(...), Bar(...), ...]
        bt = Backtester("MESH6", tick_size=0.25, tick_value=1.25)
        result = bt.run(bars)
        print(result.summary())
    """

    def __init__(
        self,
        symbol: str,
        tick_size: float,
        tick_value: float,
        allow_shorts: bool = True,
        starting_capital: float = config.STARTING_CAPITAL,
        max_daily_loss: float = config.MAX_DAILY_LOSS,
        **strategy_kwargs,
    ):
        self.symbol = symbol
        self.tick_size = tick_size
        self.tick_value = tick_value
        self.allow_shorts = allow_shorts
        self.starting_capital = starting_capital
        self.max_daily_loss = max_daily_loss
        self.strategy_kwargs = strategy_kwargs

    def run(self, bars: list[Bar]) -> BacktestResult:
        """
        Feed bars through the strategy and collect trades.
        No look-ahead bias: each bar is processed sequentially.
        """
        strategy = ElephantBarStrategy(
            symbol=self.symbol,
            tick_size=self.tick_size,
            allow_shorts=self.allow_shorts,
            **self.strategy_kwargs,
        )

        result = BacktestResult(
            symbol=self.symbol,
            starting_capital=self.starting_capital,
        )

        pending_entry: Optional[Signal] = None
        daily_pnl = 0.0

        for bar in bars:
            # Kill switch check
            if daily_pnl <= -self.max_daily_loss:
                logger.info("Kill switch hit at $%.2f loss. Stopping.", daily_pnl)
                break

            # Check if a pending entry would have filled on this bar
            if pending_entry is not None:
                filled = False
                if pending_entry.direction == "LONG" and bar.high >= pending_entry.entry_price:
                    filled = True
                elif pending_entry.direction == "SHORT" and bar.low <= pending_entry.entry_price:
                    filled = True

                if filled:
                    strategy.register_fill(pending_entry)
                    logger.debug(
                        "Fill: %s %s @ %.4f",
                        pending_entry.direction, self.symbol, pending_entry.entry_price,
                    )
                else:
                    # Entry not triggered — cancel it
                    pending_entry = None

            # Process the bar
            signals = strategy.on_bar(bar)

            for signal in signals:
                if signal.signal_type == "ENTRY":
                    # Queue entry for next bar fill check (avoid look-ahead)
                    pending_entry = signal

                elif signal.signal_type in ("PUSH_EXIT", "STOP_EXIT"):
                    if strategy.open_trade is None and pending_entry is not None:
                        # Trade was just closed by strategy's on_bar
                        exit_price = signal.entry_price
                        entry_signal = pending_entry
                    elif pending_entry is not None:
                        exit_price = signal.entry_price
                        entry_signal = pending_entry
                    else:
                        continue

                    trade = Trade(
                        symbol=self.symbol,
                        direction=signal.direction,
                        entry_price=entry_signal.entry_price,
                        exit_price=exit_price,
                        stop_price=entry_signal.stop_price,
                        entry_timestamp=entry_signal.bar_timestamp,
                        exit_timestamp=signal.bar_timestamp,
                        exit_reason=signal.signal_type,
                        tick_size=self.tick_size,
                        tick_value=self.tick_value,
                    )
                    result.trades.append(trade)
                    daily_pnl += trade.pnl
                    pending_entry = None

                    logger.debug(
                        "Trade closed (%s): %s P&L=$%.2f",
                        trade.exit_reason, trade.direction, trade.pnl,
                    )

        return result


def load_bars_from_csv(filepath: str) -> list[Bar]:
    """
    Load bars from a CSV file with columns: timestamp, open, high, low, close, volume.
    Supports standard OHLCV exports from TradingView, Sierra Chart, etc.
    """
    import csv

    bars = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Try common column name variations
            ts = row.get("timestamp") or row.get("time") or row.get("date") or row.get("Date") or "0"
            bars.append(Bar(
                timestamp=float(ts) if ts.replace(".", "").replace("-", "").isdigit() else hash(ts),
                open=float(row.get("open") or row.get("Open") or 0),
                high=float(row.get("high") or row.get("High") or 0),
                low=float(row.get("low") or row.get("Low") or 0),
                close=float(row.get("close") or row.get("Close") or 0),
                volume=float(row.get("volume") or row.get("Volume") or 0),
            ))
    return bars
