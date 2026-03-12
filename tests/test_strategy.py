"""Tests for the Elephant Bar strategy core logic."""
import pytest
from src.strategy.core import Bar, Signal, ElephantBarStrategy


def make_bar(ts, open_, high, low, close, volume=100.0) -> Bar:
    """Helper to create a Bar quickly."""
    return Bar(timestamp=ts, open=open_, high=high, low=low, close=close, volume=volume)


def make_flat_bars(count: int, price: float = 5000.0, body: float = 1.0) -> list[Bar]:
    """Generate `count` small-bodied bars hovering around `price`."""
    bars = []
    for i in range(count):
        o = price
        c = price + body
        h = max(o, c) + 0.25
        l = min(o, c) - 0.25
        bars.append(make_bar(ts=float(i), open_=o, high=h, low=l, close=c))
    return bars


class TestBar:
    def test_body(self):
        bar = make_bar(0, 100.0, 105.0, 99.0, 104.0)
        assert bar.body == 4.0

    def test_bullish(self):
        bar = make_bar(0, 100.0, 105.0, 99.0, 104.0)
        assert bar.is_bullish is True
        assert bar.is_bearish is False

    def test_bearish(self):
        bar = make_bar(0, 104.0, 105.0, 99.0, 100.0)
        assert bar.is_bearish is True
        assert bar.is_bullish is False

    def test_full_range(self):
        bar = make_bar(0, 100.0, 110.0, 95.0, 105.0)
        assert bar.full_range == 15.0

    def test_no_tail_true(self):
        # Body fills 95%+ of the range
        bar = make_bar(0, 100.0, 110.1, 99.9, 110.0)
        assert bar.is_no_tail is True

    def test_no_tail_false(self):
        # Body is only 50% of range
        bar = make_bar(0, 100.0, 110.0, 90.0, 105.0)
        assert bar.is_no_tail is False

    def test_no_tail_zero_range(self):
        bar = make_bar(0, 100.0, 100.0, 100.0, 100.0)
        assert bar.is_no_tail is False


class TestStrategy:
    """Test the ElephantBarStrategy detection and signal logic."""

    def _make_strategy(self, **kwargs) -> ElephantBarStrategy:
        defaults = dict(
            symbol="MESH6",
            tick_size=0.25,
            allow_shorts=True,
            sma_fast=20,
            sma_slow=50,  # Use 50 instead of 200 so tests need fewer bars
            atr_period=14,
            narrow_threshold=1.0,
            elephant_mult=2.0,
            avg_body_period=20,
            push_exit_count=6,
        )
        defaults.update(kwargs)
        return ElephantBarStrategy(**defaults)

    def test_no_signal_before_warmup(self):
        """Strategy should not emit signals until enough bars for slow SMA."""
        strat = self._make_strategy(sma_slow=50)
        bars = make_flat_bars(30)
        for bar in bars:
            signals = strat.on_bar(bar)
            assert signals == []

    def test_elephant_bar_long_signal(self):
        """A bullish elephant bar with narrow SMAs should produce a LONG entry."""
        strat = self._make_strategy(sma_slow=50)

        # Feed 50 flat bars to satisfy SMA requirement
        warmup = make_flat_bars(51, price=5000.0, body=1.0)
        for bar in warmup:
            strat.on_bar(bar)

        # Now send an elephant bar: body = 5.0 which is 5x the avg body of 1.0
        # Must also be no-tail (body >= 90% of range)
        elephant = make_bar(
            ts=100.0, open_=5000.0, high=5005.1, low=4999.9, close=5005.0
        )
        signals = strat.on_bar(elephant)

        assert len(signals) == 1
        sig = signals[0]
        assert sig.direction == "LONG"
        assert sig.signal_type == "ENTRY"
        assert sig.entry_price == elephant.high + 0.25  # 1 tick above high
        assert sig.stop_price == elephant.low

    def test_elephant_bar_short_signal(self):
        """A bearish elephant bar should produce a SHORT entry."""
        strat = self._make_strategy(sma_slow=50)

        warmup = make_flat_bars(51, price=5000.0, body=1.0)
        for bar in warmup:
            strat.on_bar(bar)

        elephant = make_bar(
            ts=100.0, open_=5005.0, high=5005.1, low=4999.9, close=5000.0
        )
        signals = strat.on_bar(elephant)

        assert len(signals) == 1
        sig = signals[0]
        assert sig.direction == "SHORT"
        assert sig.entry_price == elephant.low - 0.25

    def test_shorts_disabled(self):
        """Bearish elephant bar should NOT signal when shorts are disabled."""
        strat = self._make_strategy(sma_slow=50, allow_shorts=False)

        warmup = make_flat_bars(51, price=5000.0, body=1.0)
        for bar in warmup:
            strat.on_bar(bar)

        elephant = make_bar(
            ts=100.0, open_=5005.0, high=5005.1, low=4999.9, close=5000.0
        )
        signals = strat.on_bar(elephant)
        assert signals == []

    def test_non_elephant_no_signal(self):
        """A normal-sized bar should not trigger a signal."""
        strat = self._make_strategy(sma_slow=50)

        warmup = make_flat_bars(51, price=5000.0, body=1.0)
        for bar in warmup:
            strat.on_bar(bar)

        # Bar with body = 1.5, which is < 2x avg body of 1.0
        normal = make_bar(ts=100.0, open_=5000.0, high=5001.6, low=4999.9, close=5001.5)
        signals = strat.on_bar(normal)
        assert signals == []

    def test_stop_loss_exit(self):
        """When price hits the stop, a STOP_EXIT signal should fire."""
        strat = self._make_strategy(sma_slow=50)

        warmup = make_flat_bars(51, price=5000.0, body=1.0)
        for bar in warmup:
            strat.on_bar(bar)

        # Trigger entry
        elephant = make_bar(
            ts=100.0, open_=5000.0, high=5005.1, low=4999.9, close=5005.0
        )
        entry_signals = strat.on_bar(elephant)
        assert len(entry_signals) == 1

        # Register fill
        strat.register_fill(entry_signals[0])
        assert strat.is_in_trade is True

        # Bar that hits the stop (low <= stop_price which is 4999.9)
        stop_bar = make_bar(ts=101.0, open_=5003.0, high=5004.0, low=4999.5, close=5000.0)
        signals = strat.on_bar(stop_bar)

        assert len(signals) == 1
        assert signals[0].signal_type == "STOP_EXIT"
        assert strat.is_in_trade is False

    def test_push_exit(self):
        """After N consecutive new highs, a PUSH_EXIT signal should fire."""
        strat = self._make_strategy(sma_slow=50, push_exit_count=3)

        warmup = make_flat_bars(51, price=5000.0, body=1.0)
        for bar in warmup:
            strat.on_bar(bar)

        # Entry
        elephant = make_bar(
            ts=100.0, open_=5000.0, high=5005.1, low=4999.9, close=5005.0
        )
        entry_signals = strat.on_bar(elephant)
        strat.register_fill(entry_signals[0])

        # 3 consecutive higher highs (push_exit_count=3)
        signals = []
        for i in range(3):
            push_bar = make_bar(
                ts=101.0 + i,
                open_=5005.0 + i,
                high=5006.0 + i,  # Each makes a new high
                low=5004.0 + i,
                close=5005.5 + i,
            )
            signals = strat.on_bar(push_bar)

        assert len(signals) == 1
        assert signals[0].signal_type == "PUSH_EXIT"
        assert strat.is_in_trade is False

    def test_register_fill_and_close(self):
        """register_fill opens a trade, close_trade clears it."""
        strat = self._make_strategy()
        assert strat.is_in_trade is False

        signal = Signal(
            direction="LONG", entry_price=5000.0, stop_price=4990.0,
            symbol="MESH6", bar_timestamp=1.0,
        )
        strat.register_fill(signal)
        assert strat.is_in_trade is True

        strat.close_trade()
        assert strat.is_in_trade is False


class TestIndicators:
    """Test the internal indicator calculations."""

    def _make_strategy(self, **kwargs) -> ElephantBarStrategy:
        defaults = dict(symbol="MESH6", tick_size=0.25, sma_fast=5, sma_slow=10, atr_period=5)
        defaults.update(kwargs)
        return ElephantBarStrategy(**defaults)

    def test_sma_calculation(self):
        strat = self._make_strategy(sma_fast=3)
        bars = [
            make_bar(0, 10, 11, 9, 10),
            make_bar(1, 10, 11, 9, 20),
            make_bar(2, 10, 11, 9, 30),
        ]
        for b in bars:
            strat.bars.append(b)

        sma = strat._sma(3)
        assert sma == pytest.approx(20.0)  # (10 + 20 + 30) / 3

    def test_sma_insufficient_bars(self):
        strat = self._make_strategy()
        strat.bars.append(make_bar(0, 10, 11, 9, 10))
        assert strat._sma(5) is None

    def test_atr_calculation(self):
        strat = self._make_strategy(atr_period=2)
        # 3 bars needed for ATR period of 2
        bars = [
            make_bar(0, 100, 105, 95, 100),   # prev for ATR calc
            make_bar(1, 100, 110, 90, 105),    # TR = max(20, 10, 10) = 20
            make_bar(2, 105, 115, 100, 110),   # TR = max(15, 10, 5) = 15
        ]
        for b in bars:
            strat.bars.append(b)

        atr = strat._atr()
        assert atr == pytest.approx(17.5)  # (20 + 15) / 2

    def test_avg_body(self):
        strat = self._make_strategy(avg_body_period=3)
        bars = [
            make_bar(0, 100, 110, 90, 105),   # body = 5
            make_bar(1, 100, 110, 90, 110),   # body = 10
            make_bar(2, 100, 110, 90, 103),   # body = 3
        ]
        for b in bars:
            strat.bars.append(b)

        avg = strat._avg_body()
        assert avg == pytest.approx(6.0)  # (5 + 10 + 3) / 3
