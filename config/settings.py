"""
Configuration settings for the Alpaca Elephant Bar trading bot.
"""

import os

# ── Mode ────────────────────────────────────────────────────────────────
PAPER_MODE = os.getenv("ALPACA_PAPER", "true").lower() == "true"

# ── Alpaca API keys (set via environment variables) ─────────────────────
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = (
    "https://paper-api.alpaca.markets"
    if PAPER_MODE
    else "https://api.alpaca.markets"
)
ALPACA_DATA_FEED = os.getenv("ALPACA_DATA_FEED", "iex")  # "iex" or "sip"

# ── Watchlist ───────────────────────────────────────────────────────────
WATCHLIST = [
    "AAPL", "AMD", "AMZN", "ASML", "CRWD",
    "DIS", "DRI", "GOOGL", "INTC", "META",
    "MSFT", "MU", "NVDA", "ORCL", "PAAS",
    "RIVN", "RMBS", "SIL", "SNDK", "SYNA",
    "TSLA", "TSM", "URNM", "WDC", "WPM",
]

# ── Market Condition (SPY) ──────────────────────────────────────────────
MARKET_TICKER = "SPY"
MARKET_MA_SHORT = 20
MARKET_MA_LONG = 200

# ── Trading Window ──────────────────────────────────────────────────────
# Override via env: TRADING_WINDOW_MINUTES=20 (duration from start or late join)
TRADING_START_HOUR = 9
TRADING_START_MINUTE = 30
TRADING_END_HOUR = 9
TRADING_END_MINUTE = 50
TRADING_WINDOW_MINUTES = int(os.getenv("TRADING_WINDOW_MINUTES", "20"))

# ── Elephant Bar Strategy Parameters ────────────────────────────────────
ELEPHANT_BAR_LOOKBACK = 20          # candles to average for body-size comparison
ELEPHANT_BAR_MULTIPLIER = 2.5       # body must be N× the average
VOLUME_SPIKE_MULTIPLIER = 1.5       # volume must exceed N× average
MA200_PERIOD = 200                  # long-term trend filter

# ── Risk Management ────────────────────────────────────────────────────
MAX_RISK_PER_TRADE_PCT = 1.0        # % of equity risked per trade
STOP_LOSS_ATR_MULT = 1.5            # stop at N× ATR from entry
TAKE_PROFIT_RR = 2.0                # reward : risk ratio for target
MAX_POSITIONS = 3                   # concurrent open positions
MAX_DAILY_LOSS_PCT = 3.0            # session hard stop (% of equity)

# ── Screener Thresholds ────────────────────────────────────────────────
SCREENER_MIN_PRICE = 5.0
SCREENER_MAX_PRICE = 500.0
SCREENER_MIN_AVG_VOLUME = 500_000   # 20-day avg daily volume
SCREENER_MIN_ATR_PCT = 1.0          # ATR as % of price (volatility)

# ── Historical Data ────────────────────────────────────────────────────
HISTORICAL_BARS_DAYS = 400          # days of daily bars for MA200 warmup

# ── Output ──────────────────────────────────────────────────────────────
TRADE_LOG_PATH = "results/trades.csv"

# ── Notifications (stub — extend for Discord / Telegram / etc.) ────────
NOTIFY_ENABLED = os.getenv("NOTIFY_ENABLED", "true").lower() == "true"
