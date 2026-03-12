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
ELEPHANT_MULT = 2.0    # Candle body must be >= this x avg body size
AVG_BODY_PERIOD = 20   # Lookback for average body size calculation
PROXIMITY_ATR = 1.5    # Color-game add-on: bar must be within this x ATR of 20 SMA
PUSH_EXIT_COUNT = 6    # Number of consecutive new highs/lows to trigger exit

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
    "SIL": {"tick_size": 0.005, "tick_value": 5.00, "multiplier": 1000},
}

# 1-hour longs-only subset
CONTRACTS_1HR = {
    "MES": CONTRACTS_2MIN["MES"],
    "MCL": CONTRACTS_2MIN["MCL"],
    "MGC": CONTRACTS_2MIN["MGC"],
    "SIL": CONTRACTS_2MIN["SIL"],
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
