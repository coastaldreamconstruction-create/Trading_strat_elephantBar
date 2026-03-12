"""Tests for the backtesting engine."""
import pytest
from src.strategy.core import Bar
from src.backtest.engine import Backtester, BacktestResult, Trade


def make_bar(ts, open_, high, low, close, volume=100.0) -> Bar:
    return Bar(timestamp=ts, open=open_, high=high, low=low, close=close, volume=volume)


def make_flat_bars(count: int, price: float = 5000.0, body: float = 1.0) -> list[Bar]:
    bars = []
    for i in range(count):
        o = price
        c = price + body
        h = max(o, c) + 0.25
        l = min(o, c) - 0.25
        bars.append(make_bar(ts=float(i), open_=o, high=h, low=l, close=c))
    return bars


class TestTrade:
    def test_long_winner(self):
        trade = Trade(
            symbol="MESH6", direction="LONG",
            entry_price=5000.0, exit_price=5010.0, stop_price=4990.0,
            entry_timestamp=0, exit_timestamp=1, exit_reason="PUSH_EXIT",
            tick_size=0.25, tick_value=1.25,
        )
        assert trade.price_diff == 10.0
        assert trade.ticks_gained == 40.0
        assert trade.pnl == 50.0
        assert trade.is_winner is True

    def test_long_loser(self):
        trade = Trade(
            symbol="MESH6", direction="LONG",
            entry_price=5000.0, exit_price=4990.0, stop_price=4990.0,
            entry_timestamp=0, exit_timestamp=1, exit_reason="STOP_EXIT",
            tick_size=0.25, tick_value=1.25,
        )
        assert trade.pnl == -50.0
        assert trade.is_winner is False

    def test_short_winner(self):
        trade = Trade(
            symbol="MESH6", direction="SHORT",
            entry_price=5000.0, exit_price=4990.0, stop_price=5010.0,
            entry_timestamp=0, exit_timestamp=1, exit_reason="PUSH_EXIT",
            tick_size=0.25, tick_value=1.25,
        )
        assert trade.pnl == 50.0
        assert trade.is_winner is True


class TestBacktestResult:
    def test_empty_result(self):
        result = BacktestResult(symbol="MESH6")
        assert result.total_trades == 0
        assert result.win_rate == 0.0
        assert result.total_pnl == 0.0
        assert result.max_drawdown == 0.0
        assert result.profit_factor == 0.0

    def test_summary_with_trades(self):
        result = BacktestResult(symbol="MESH6", starting_capital=25000)
        result.trades = [
            Trade("MESH6", "LONG", 5000, 5010, 4990, 0, 1, "PUSH_EXIT", 0.25, 1.25),
            Trade("MESH6", "LONG", 5020, 5010, 5000, 2, 3, "STOP_EXIT", 0.25, 1.25),
        ]
        assert result.total_trades == 2
        assert result.win_rate == 0.5
        assert len(result.equity_curve) == 3
        summary = result.summary()
        assert "MESH6" in summary

    def test_max_drawdown(self):
        result = BacktestResult(symbol="TEST", starting_capital=10000)
        result.trades = [
            Trade("T", "LONG", 100, 90, 90, 0, 1, "STOP_EXIT", 1, 1),   # -10
            Trade("T", "LONG", 100, 90, 90, 2, 3, "STOP_EXIT", 1, 1),   # -10
            Trade("T", "LONG", 100, 120, 90, 4, 5, "PUSH_EXIT", 1, 1),  # +20
        ]
        # Equity: 10000 -> 9990 -> 9980 -> 10000
        # Peak was 10000, trough was 9980, drawdown = 20
        assert result.max_drawdown == 20.0


class TestBacktester:
    def test_run_no_signals_on_flat_data(self):
        """Flat data should produce zero trades."""
        bt = Backtester("MESH6", tick_size=0.25, tick_value=1.25, sma_slow=50)
        bars = make_flat_bars(100, price=5000.0, body=1.0)
        result = bt.run(bars)
        assert result.total_trades == 0

    def test_run_produces_result(self):
        """Backtester should return a BacktestResult even with no trades."""
        bt = Backtester("MESH6", tick_size=0.25, tick_value=1.25)
        bars = make_flat_bars(10)
        result = bt.run(bars)
        assert isinstance(result, BacktestResult)
        assert result.symbol == "MESH6"
