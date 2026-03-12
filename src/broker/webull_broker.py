"""
Elephant Bar Breakout Strategy — Webull Broker Adapter
Wraps the official Webull OpenAPI Python SDK for order execution and data retrieval.
"""
import uuid
import logging
from datetime import datetime
from typing import Optional

from src import config

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Contract symbol builder
# ─────────────────────────────────────────────
def get_front_month_symbol(root: str, ref_date: Optional[datetime] = None) -> str:
    """
    Build a full futures symbol like 'MESH6' from root 'MES'.
    Picks the current front-month contract based on today's date.
    """
    if ref_date is None:
        ref_date = datetime.utcnow()
    month = ref_date.month
    year = ref_date.year % 100

    quarterly_roots = {"MES", "MNQ", "MYM"}
    if root in quarterly_roots:
        quarterly_months = [3, 6, 9, 12]
        for qm in quarterly_months:
            if month <= qm:
                code = config.MONTH_CODES[qm]
                return f"{root}{code}{year}"
        code = config.MONTH_CODES[3]
        return f"{root}{code}{(year + 1)}"

    if month == 12:
        next_month = 1
        sym_year = year + 1
    else:
        next_month = month + 1
        sym_year = year
    code = config.MONTH_CODES[next_month]
    return f"{root}{code}{sym_year}"


# ─────────────────────────────────────────────
# Broker Adapter
# ─────────────────────────────────────────────
class WebullBroker:
    """
    Manages connection to Webull OpenAPI for futures trading.
    """

    def __init__(self):
        self.app_key = config.WEBULL_APP_KEY
        self.app_secret = config.WEBULL_APP_SECRET
        self.region = config.WEBULL_REGION
        self.account_id = config.WEBULL_ACCOUNT_ID
        self.endpoint = (
            config.WEBULL_TEST_ENDPOINT if config.USE_PAPER
            else config.WEBULL_API_ENDPOINT
        )
        self.api_client = None
        self.trade_client = None
        self.data_client = None

    def connect(self):
        """Initialize SDK clients."""
        try:
            from webullsdkcore.client import ApiClient
            from webullsdktrade.trade_client import TradeClient
            from webullsdkmdata.data_client import DataClient
            from webullsdkcore.common.region import Region

            self.api_client = ApiClient(self.app_key, self.app_secret, Region.US.value)
            self.api_client.add_endpoint(Region.US.value, self.endpoint)
            self.trade_client = TradeClient(self.api_client)
            self.data_client = DataClient(self.api_client)

            logger.info(
                "Connected to Webull %s (%s)",
                "PAPER" if config.USE_PAPER else "LIVE",
                self.endpoint,
            )
            return True
        except ImportError as e:
            logger.error("Webull SDK import failed: %s", e)
            return False
        except Exception as e:
            logger.error("Failed to connect to Webull: %s", e)
            return False

    # ──────────────────────────────────────────
    # Market Data
    # ──────────────────────────────────────────
    def get_historical_bars(
        self, symbol: str, timespan: str = "M1", count: int = 201
    ) -> list[dict]:
        """Fetch historical OHLCV bars for a futures symbol."""
        if self.data_client is None:
            logger.error("Not connected. Call connect() first.")
            return []
        try:
            from webullsdkcore.common.category import Category
            from webullsdkcore.common.timespan import Timespan

            ts_map = {
                "M1": Timespan.M1.name,
                "M5": Timespan.M5.name,
                "H1": Timespan.H1.name,
                "D": Timespan.D.name,
            }
            ts_value = ts_map.get(timespan, Timespan.M1.name)

            res = self.data_client.futures_market_data.get_futures_history_bars(
                symbol, Category.US_FUTURES.name, ts_value, count=count
            )
            if res.status_code == 200:
                data = res.json()
                bars = self._parse_bars(data)
                logger.debug("Fetched %d bars for %s", len(bars), symbol)
                return bars
            else:
                logger.warning(
                    "Bar fetch failed for %s: HTTP %s", symbol, res.status_code
                )
                return []
        except Exception as e:
            logger.error("Error fetching bars for %s: %s", symbol, e)
            return []

    def get_snapshot(self, symbol: str) -> Optional[dict]:
        """Get real-time snapshot (last price, bid, ask, etc.)."""
        if self.data_client is None:
            return None
        try:
            from webullsdkcore.common.category import Category
            res = self.data_client.futures_market_data.get_futures_snapshot(
                symbol, Category.US_FUTURES.name
            )
            if res.status_code == 200:
                return res.json()
            return None
        except Exception as e:
            logger.error("Snapshot error for %s: %s", symbol, e)
            return None

    # ──────────────────────────────────────────
    # Order Management
    # ──────────────────────────────────────────
    def place_limit_order(
        self, symbol: str, side: str, price: float, qty: int = 1, tif: str = "GTC",
    ) -> Optional[str]:
        """Place a LIMIT order for futures. Returns client_order_id or None."""
        if self.trade_client is None:
            logger.error("Not connected.")
            return None
        client_order_id = uuid.uuid4().hex
        order = [{
            "combo_type": "NORMAL",
            "client_order_id": client_order_id,
            "symbol": symbol,
            "instrument_type": "FUTURES",
            "market": "US",
            "order_type": "LIMIT",
            "limit_price": str(price),
            "quantity": str(qty),
            "side": side,
            "time_in_force": tif,
            "entrust_type": "QTY",
        }]
        try:
            res = self.trade_client.order_v3.place_order(self.account_id, order)
            if res.status_code == 200:
                logger.info(
                    "Order placed: %s %s %d %s @ %.4f [%s]",
                    side, symbol, qty, tif, price, client_order_id[:8],
                )
                return client_order_id
            else:
                logger.error("Order failed: HTTP %s — %s", res.status_code, res.text)
                return None
        except Exception as e:
            logger.error("Order error: %s", e)
            return None

    def place_stop_order(
        self, symbol: str, side: str, stop_price: float, qty: int = 1, tif: str = "GTC",
    ) -> Optional[str]:
        """Place a STOP_LOSS (market) order."""
        if self.trade_client is None:
            return None
        client_order_id = uuid.uuid4().hex
        order = [{
            "combo_type": "NORMAL",
            "client_order_id": client_order_id,
            "symbol": symbol,
            "instrument_type": "FUTURES",
            "market": "US",
            "order_type": "STOP_LOSS",
            "stop_price": str(stop_price),
            "quantity": str(qty),
            "side": side,
            "time_in_force": tif,
            "entrust_type": "QTY",
        }]
        try:
            res = self.trade_client.order_v3.place_order(self.account_id, order)
            if res.status_code == 200:
                logger.info(
                    "Stop placed: %s %s @ %.4f [%s]",
                    side, symbol, stop_price, client_order_id[:8],
                )
                return client_order_id
            else:
                logger.error("Stop failed: HTTP %s", res.status_code)
                return None
        except Exception as e:
            logger.error("Stop error: %s", e)
            return None

    def place_market_order(self, symbol: str, side: str, qty: int = 1) -> Optional[str]:
        """Place a MARKET order (for exits)."""
        if self.trade_client is None:
            return None
        client_order_id = uuid.uuid4().hex
        order = [{
            "combo_type": "NORMAL",
            "client_order_id": client_order_id,
            "symbol": symbol,
            "instrument_type": "FUTURES",
            "market": "US",
            "order_type": "MARKET",
            "quantity": str(qty),
            "side": side,
            "time_in_force": "DAY",
            "entrust_type": "QTY",
        }]
        try:
            res = self.trade_client.order_v3.place_order(self.account_id, order)
            if res.status_code == 200:
                logger.info("Market order: %s %s %d [%s]", side, symbol, qty, client_order_id[:8])
                return client_order_id
            else:
                logger.error("Market order failed: HTTP %s", res.status_code)
                return None
        except Exception as e:
            logger.error("Market order error: %s", e)
            return None

    def cancel_order(self, client_order_id: str) -> bool:
        """Cancel a pending order."""
        if self.trade_client is None:
            return False
        try:
            res = self.trade_client.order_v3.cancel_order(self.account_id, client_order_id)
            if res.status_code == 200:
                logger.info("Cancelled order %s", client_order_id[:8])
                return True
            else:
                logger.warning("Cancel failed: HTTP %s", res.status_code)
                return False
        except Exception as e:
            logger.error("Cancel error: %s", e)
            return False

    def get_open_orders(self) -> list[dict]:
        """Retrieve all open/pending orders."""
        if self.trade_client is None:
            return []
        try:
            res = self.trade_client.order_v3.get_order_open(self.account_id, page_size=50)
            if res.status_code == 200:
                return res.json()
            return []
        except Exception as e:
            logger.error("Open orders error: %s", e)
            return []

    # ──────────────────────────────────────────
    # Account
    # ──────────────────────────────────────────
    def get_account_balance(self) -> Optional[dict]:
        """Get futures account balance."""
        if self.trade_client is None:
            return None
        try:
            res = self.trade_client.account_v2.get_account_balance(self.account_id)
            if res.status_code == 200:
                return res.json()
            return None
        except Exception as e:
            logger.error("Balance error: %s", e)
            return None

    def get_positions(self) -> list[dict]:
        """Get current open positions."""
        if self.trade_client is None:
            return []
        try:
            res = self.trade_client.account_v2.get_account_position(self.account_id)
            if res.status_code == 200:
                return res.json()
            return []
        except Exception as e:
            logger.error("Positions error: %s", e)
            return []

    # ──────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────
    @staticmethod
    def _parse_bars(data) -> list[dict]:
        """Parse Webull bar response into standardized dicts."""
        bars = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("data", data.get("bars", []))
        else:
            return bars
        for item in items:
            if isinstance(item, dict):
                bars.append({
                    "timestamp": item.get("time", item.get("timestamp", 0)),
                    "open": float(item.get("open", 0)),
                    "high": float(item.get("high", 0)),
                    "low": float(item.get("low", 0)),
                    "close": float(item.get("close", 0)),
                    "volume": float(item.get("volume", item.get("vol", 0))),
                })
        return bars


def aggregate_to_2min(one_min_bars: list[dict]) -> list[dict]:
    """
    Aggregate 1-minute bars into 2-minute bars.
    Webull doesn't natively support M2, so we fetch M1 and combine pairs.
    """
    result = []
    for i in range(0, len(one_min_bars) - 1, 2):
        b1 = one_min_bars[i]
        b2 = one_min_bars[i + 1]
        result.append({
            "timestamp": b1["timestamp"],
            "open": b1["open"],
            "high": max(b1["high"], b2["high"]),
            "low": min(b1["low"], b2["low"]),
            "close": b2["close"],
            "volume": b1["volume"] + b2["volume"],
        })
    return result
