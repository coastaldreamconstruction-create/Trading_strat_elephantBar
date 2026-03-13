"""
Elephant Bar Breakout Strategy — Configuration
All tunable parameters in one place.
"""
import os

# ─────────────────────────────────────────────
# Webull API Credentials (use env vars, never commit secrets)
# ─────────────────────────────────────────────
WEBULL_APP_KEY = os.environ.get("WEBULL_APP_KEY", "")
WEBULL_APP_SECRET = os.environ.get("WEBULL_APP_SECRET", "")
WEBULL_REGION = "us"
WEBULL_ACCOUNT_ID = os.environ.get("WEBULL_ACCOUNT_ID", "")

# Endpoints
WEBULL_API_ENDPOINT = "api.webull.com"            # production
WEBULL_TEST_ENDPOINT = "us-openapi-alb.uat.webullbroker.com"  # paper/test
USE_PAPER = True  # Toggle True for paper trading, False for live

# ─────────────────────────────────────────────
# Strategy Parameters
# ─────────────────────────────────────────────
SMA_FAST = 20          # Fast SMA period (bars)
SMA_SLOW = 200         # Slow SMA period (bars)
ATR_PERIOD = 14        # ATR lookback period
NARROW_THRESHOLD = 1.0 # SMA gap must be <= this x ATR to qualify as "narrow"
ELEPHANT_MULT = 1.5    # Candle body must be >= this x avg body size
AVG_BODY_PERIOD = 20   # Lookback for average body size calculation
PROXIMITY_ATR = 1.5    # Color-game add-on: bar must be within this x ATR of 20 SMA
PUSH_EXIT_COUNT = 6    # Number of consecutive new highs/lows to trigger exit
TRAILING_STOP = False  # Enable trailing stop (moves stop to breakeven, then trails)
TRAIL_TRIGGER_ATR = 1.0  # Move stop to breakeven after price moves this x ATR in our favor
TRAIL_STEP_ATR = 0.5     # Once trailing, move stop by this x ATR on each new extreme

# Time-of-day filter (UTC hours, None = no filter)
# CME equity futures RTH: 14:30-21:00 UTC (9:30 AM - 4:00 PM ET)
TOD_START_HOUR = None    # Start hour (UTC), e.g. 14 for 2 PM UTC
TOD_END_HOUR = None      # End hour (UTC), e.g. 21 for 9 PM UTC

# Minimum ATR threshold — skip trades when volatility is too low
MIN_ATR = 0.0            # Minimum ATR value to allow entries (0 = no filter)

# ─────────────────────────────────────────────
# Timeframe
# ─────────────────────────────────────────────
BAR_INTERVAL_SECONDS = 120  # 2-minute bars (120s)

# ─────────────────────────────────────────────
# Contracts
# ─────────────────────────────────────────────
CONTRACTS_2MIN = {
    "MES": {"tick_size": 0.25, "tick_value": 1.25, "multiplier": 5},
    "MNQ": {"tick_size": 0.25, "tick_value": 0.50, "multiplier": 2},
    "MYM": {"tick_size": 1.00, "tick_value": 0.50, "multiplier": 0.5},
    "MCL": {"tick_size": 0.01, "tick_value": 1.00, "multiplier": 100},
    "MGC": {"tick_size": 0.10, "tick_value": 1.00, "multiplier": 10},
    "SICK": {"tick_size": 0.01, "tick_value": 1.00, "multiplier": 100},
}

# 1-hour longs-only subset
CONTRACTS_1HR = {
    "MES": CONTRACTS_2MIN["MES"],
    "MCL": CONTRACTS_2MIN["MCL"],
    "MGC": CONTRACTS_2MIN["MGC"],
    "SICK": CONTRACTS_2MIN["SICK"],
}

# ─────────────────────────────────────────────
# Position Sizing
# ─────────────────────────────────────────────
POSITION_SIZE = 1       # Always 1 contract per trade
STARTING_CAPITAL = 25000

# ─────────────────────────────────────────────
# Risk / Safety
# ─────────────────────────────────────────────
MAX_OPEN_TRADES = 6     # Max simultaneous open positions (one per contract)
MAX_DAILY_LOSS = 1000   # Dollar amount — kill switch if daily loss exceeds this
ENABLE_SHORTS_2MIN = True   # Shorts allowed on 2-min timeframe
ENABLE_SHORTS_1HR = False   # Shorts DISABLED on 1-hour timeframe

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
LOG_FILE = "elephant_bar.log"
LOG_LEVEL = "INFO"  # DEBUG for development, INFO for production

# ─────────────────────────────────────────────
# Contract Month Codes (CME standard)
# ─────────────────────────────────────────────
MONTH_CODES = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
}
