"""
Elephant Bar Breakout Strategy — Core Signal Logic
Pure computation, no broker dependency. Easy to unit-test and backtest.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src import config


@dataclass
class Bar:
    """Single OHLCV bar."""
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def full_range(self) -> float:
        return self.high - self.low

    @property
    def is_no_tail(self) -> bool:
        """True if elephant bar has no significant tail (body fills the candle)."""
        if self.full_range == 0:
            return False
        return self.body / self.full_range >= 0.90  # 90%+ body-to-range ratio


@dataclass
class Signal:
    """Trade signal emitted by the strategy."""
    direction: str          # "LONG" or "SHORT"
    entry_price: float      # 1 tick above high (long) or below low (short)
    stop_price: float       # Full wick low (long) or high (short)
    symbol: str
    bar_timestamp: float
    signal_type: str = "ENTRY"  # "ENTRY", "ADDON", "PUSH_EXIT", "STOP_EXIT"


@dataclass
class OpenTrade:
    """Tracks an active position."""
    symbol: str
    direction: str              # "LONG" or "SHORT"
    entry_price: float
    stop_price: float
    push_count: int = 0         # Consecutive new highs/lows
    best_price: float = 0.0     # Tracks highest high (long) or lowest low (short)
    addon_triggered: bool = False
    entry_bar_timestamp: float = 0.0


class ElephantBarStrategy:
    """
    Stateful strategy engine. Feed bars one at a time via `on_bar()`.
    Returns a list of Signal objects (can be empty).
    """

    def __init__(
        self,
        symbol: str,
        tick_size: float,
        allow_shorts: bool = True,
        sma_fast: int = config.SMA_FAST,
        sma_slow: int = config.SMA_SLOW,
        atr_period: int = config.ATR_PERIOD,
        narrow_threshold: float = config.NARROW_THRESHOLD,
        elephant_mult: float = config.ELEPHANT_MULT,
        avg_body_period: int = config.AVG_BODY_PERIOD,
        proximity_atr: float = config.PROXIMITY_ATR,
        push_exit_count: int = config.PUSH_EXIT_COUNT,
        trailing_stop: bool = config.TRAILING_STOP,
        trail_trigger_atr: float = config.TRAIL_TRIGGER_ATR,
        trail_step_atr: float = config.TRAIL_STEP_ATR,
        tod_start_hour: Optional[int] = config.TOD_START_HOUR,
        tod_end_hour: Optional[int] = config.TOD_END_HOUR,
        min_atr: float = config.MIN_ATR,
        skip_narrow: bool = False,
    ):
        self.symbol = symbol
        self.tick_size = tick_size
        self.allow_shorts = allow_shorts

        # Parameters
        self.sma_fast_period = sma_fast
        self.sma_slow_period = sma_slow
        self.atr_period = atr_period
        self.narrow_threshold = narrow_threshold
        self.elephant_mult = elephant_mult
        self.avg_body_period = avg_body_period
        self.proximity_atr = proximity_atr
        self.push_exit_count = push_exit_count
        self.trailing_stop = trailing_stop
        self.trail_trigger_atr = trail_trigger_atr
        self.trail_step_atr = trail_step_atr
        self.tod_start_hour = tod_start_hour
        self.tod_end_hour = tod_end_hour
        self.min_atr = min_atr
        self.skip_narrow = skip_narrow

        # State
        self.bars: list[Bar] = []
        self.open_trade: Optional[OpenTrade] = None

    # ──────────────────────────────────────────
    # Indicators
    # ──────────────────────────────────────────
    def _sma(self, period: int) -> Optional[float]:
        """Simple moving average of close prices."""
        if len(self.bars) < period:
            return None
        closes = [b.close for b in self.bars[-period:]]
        return sum(closes) / period

    def _atr(self) -> Optional[float]:
        """Average True Range over atr_period bars."""
        if len(self.bars) < self.atr_period + 1:
            return None
        trs = []
        for i in range(-self.atr_period, 0):
            bar = self.bars[i]
            prev = self.bars[i - 1]
            tr = max(
                bar.high - bar.low,
                abs(bar.high - prev.close),
                abs(bar.low - prev.close),
            )
            trs.append(tr)
        return sum(trs) / len(trs)

    def _avg_body(self) -> Optional[float]:
        """Average candle body size over lookback period."""
        period = min(self.avg_body_period, len(self.bars))
        if period == 0:
            return None
        bodies = [b.body for b in self.bars[-period:]]
        return sum(bodies) / period

    # ──────────────────────────────────────────
    # Conditions
    # ──────────────────────────────────────────
    def _is_narrow(self, sma_fast: float, sma_slow: float, atr: float) -> bool:
        """Are the two SMAs close together (gap <= threshold x ATR)?"""
        if atr == 0:
            return False
        gap = abs(sma_fast - sma_slow)
        return gap <= self.narrow_threshold * atr

    def _is_elephant(self, bar: Bar, avg_body: float) -> bool:
        """Is this candle an elephant bar (body >= multiplier x avg body)?"""
        if avg_body == 0:
            return False
        return bar.body >= self.elephant_mult * avg_body

    def _in_trading_hours(self, bar: Bar) -> bool:
        """Check if bar falls within allowed trading hours (UTC)."""
        if self.tod_start_hour is None or self.tod_end_hour is None:
            return True  # No filter
        try:
            hour = datetime.fromtimestamp(bar.timestamp, tz=timezone.utc).hour
        except (OSError, ValueError):
            return True  # Bad timestamp, don't filter
        if self.tod_start_hour <= self.tod_end_hour:
            return self.tod_start_hour <= hour < self.tod_end_hour
        else:
            # Wraps midnight (e.g. 22 to 6)
            return hour >= self.tod_start_hour or hour < self.tod_end_hour

    def _meets_min_atr(self, atr: float) -> bool:
        """Check if current ATR meets the minimum threshold."""
        if self.min_atr <= 0:
            return True
        return atr >= self.min_atr

    def _is_color_game_candidate(self, bar: Bar, sma_fast: float, atr: float) -> bool:
        """
        Color-game add-on: small opposing-color bar near the 20 SMA.
        Must be within proximity_atr x ATR of the 20 SMA.
        """
        if self.open_trade is None:
            return False
        # Must be opposing color
        if self.open_trade.direction == "LONG" and bar.is_bullish:
            return False
        if self.open_trade.direction == "SHORT" and bar.is_bearish:
            return False
        # Must be near the 20 SMA
        bar_mid = (bar.high + bar.low) / 2
        distance = abs(bar_mid - sma_fast)
        return distance <= self.proximity_atr * atr

    # ──────────────────────────────────────────
    # Push counting (exit logic)
    # ──────────────────────────────────────────
    def _update_pushes(self, bar: Bar) -> bool:
        """
        Update push count for the open trade.
        Returns True if exit threshold reached.
        """
        if self.open_trade is None:
            return False
        trade = self.open_trade

        if trade.direction == "LONG":
            if bar.high > trade.best_price:
                trade.best_price = bar.high
                trade.push_count += 1
            else:
                # Reset on a bar that doesn't make a new high
                trade.push_count = 0
                trade.best_price = bar.high
        else:  # SHORT
            if trade.best_price == 0.0:
                trade.best_price = bar.low
            if bar.low < trade.best_price:
                trade.best_price = bar.low
                trade.push_count += 1
            else:
                trade.push_count = 0
                trade.best_price = bar.low

        return trade.push_count >= self.push_exit_count

    def _update_trailing_stop(self, bar: Bar):
        """
        Trail the stop loss when enabled.
        Phase 1: Once price moves trail_trigger_atr x ATR in our favor, move stop to breakeven.
        Phase 2: Continue trailing by trail_step_atr x ATR on each new extreme.
        """
        if not self.trailing_stop or self.open_trade is None:
            return

        atr = self._atr()
        if atr is None or atr == 0:
            return

        trade = self.open_trade
        trigger_dist = self.trail_trigger_atr * atr
        trail_offset = self.trail_step_atr * atr

        if trade.direction == "LONG":
            favorable_move = bar.high - trade.entry_price
            if favorable_move >= trigger_dist:
                # Trail: new stop = highest high - trail_offset, but never below current stop
                new_stop = trade.best_price - trail_offset
                if new_stop > trade.stop_price:
                    trade.stop_price = new_stop
        else:  # SHORT
            favorable_move = trade.entry_price - bar.low
            if favorable_move >= trigger_dist:
                new_stop = trade.best_price + trail_offset
                if new_stop < trade.stop_price:
                    trade.stop_price = new_stop

    def _check_stop(self, bar: Bar) -> bool:
        """Returns True if stop loss has been hit."""
        if self.open_trade is None:
            return False
        if self.open_trade.direction == "LONG":
            return bar.low <= self.open_trade.stop_price
        else:
            return bar.high >= self.open_trade.stop_price

    # ──────────────────────────────────────────
    # Main entry point
    # ──────────────────────────────────────────
    def on_bar(self, bar: Bar) -> list[Signal]:
        """
        Process a new bar. Returns list of signals (entry, addon, exit, stop).
        """
        self.bars.append(bar)
        signals = []

        # Need enough history for the slow SMA
        if len(self.bars) < self.sma_slow_period + 1:
            return signals

        # Compute indicators
        sma_fast = self._sma(self.sma_fast_period)
        sma_slow = self._sma(self.sma_slow_period)
        atr = self._atr()
        avg_body = self._avg_body()

        if any(v is None for v in [sma_fast, sma_slow, atr, avg_body]):
            return signals

        # ── Manage existing trade ──
        if self.open_trade is not None:
            # Update trailing stop before checking it
            self._update_trailing_stop(bar)

            # Check stop loss
            if self._check_stop(bar):
                signals.append(Signal(
                    direction=self.open_trade.direction,
                    entry_price=self.open_trade.stop_price,
                    stop_price=0,
                    symbol=self.symbol,
                    bar_timestamp=bar.timestamp,
                    signal_type="STOP_EXIT",
                ))
                self.open_trade = None
                return signals

            # Check push exit
            if self._update_pushes(bar):
                signals.append(Signal(
                    direction=self.open_trade.direction,
                    entry_price=bar.close,  # exit at close
                    stop_price=0,
                    symbol=self.symbol,
                    bar_timestamp=bar.timestamp,
                    signal_type="PUSH_EXIT",
                ))
                self.open_trade = None
                return signals

            # Check color-game add-on
            if (not self.open_trade.addon_triggered
                    and self._is_color_game_candidate(bar, sma_fast, atr)):
                self.open_trade.addon_triggered = True

            return signals

        # ── Look for new entry ──
        narrow = True if self.skip_narrow else self._is_narrow(sma_fast, sma_slow, atr)
        elephant = self._is_elephant(bar, avg_body)
        no_tail = bar.is_no_tail

        # Apply optional filters
        if not self._in_trading_hours(bar):
            return signals
        if not self._meets_min_atr(atr):
            return signals

        if narrow and elephant and no_tail:
            # Long signal
            if bar.is_bullish:
                entry = bar.high + self.tick_size  # 1 tick above high
                stop = bar.low  # Full wick low
                signals.append(Signal(
                    direction="LONG",
                    entry_price=entry,
                    stop_price=stop,
                    symbol=self.symbol,
                    bar_timestamp=bar.timestamp,
                ))
            # Short signal
            elif bar.is_bearish and self.allow_shorts:
                entry = bar.low - self.tick_size  # 1 tick below low
                stop = bar.high  # Full wick high
                signals.append(Signal(
                    direction="SHORT",
                    entry_price=entry,
                    stop_price=stop,
                    symbol=self.symbol,
                    bar_timestamp=bar.timestamp,
                ))

        return signals

    def register_fill(self, signal: Signal):
        """Call this once the broker confirms a fill on an entry signal."""
        self.open_trade = OpenTrade(
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=signal.entry_price,
            stop_price=signal.stop_price,
            push_count=0,
            best_price=signal.entry_price,
            addon_triggered=False,
            entry_bar_timestamp=signal.bar_timestamp,
        )

    def close_trade(self):
        """Manually close the current trade (e.g., on exit signal)."""
        self.open_trade = None

    @property
    def is_in_trade(self) -> bool:
        return self.open_trade is not None
