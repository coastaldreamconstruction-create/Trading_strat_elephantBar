"""Tests for broker utilities (no SDK required)."""
from datetime import datetime
from src.broker.webull_broker import get_front_month_symbol, aggregate_to_2min, WebullBroker


class TestFrontMonthSymbol:
    def test_quarterly_march(self):
        dt = datetime(2026, 1, 15)
        assert get_front_month_symbol("MES", dt) == "MESH26"

    def test_quarterly_june(self):
        dt = datetime(2026, 4, 1)
        assert get_front_month_symbol("MES", dt) == "MESM26"

    def test_quarterly_september(self):
        dt = datetime(2026, 7, 1)
        assert get_front_month_symbol("MNQ", dt) == "MNQU26"

    def test_quarterly_december(self):
        dt = datetime(2026, 10, 1)
        assert get_front_month_symbol("MYM", dt) == "MYMZ26"

    def test_quarterly_rollover_to_next_year(self):
        dt = datetime(2026, 12, 15)  # Past December, rolls to March next year
        # month=12, last qm is 12, so 12 <= 12 -> code for 12 = Z
        assert get_front_month_symbol("MES", dt) == "MESZ26"

    def test_non_quarterly_contract(self):
        dt = datetime(2026, 3, 1)
        # MCL is not quarterly, so next month = 4, code = J
        assert get_front_month_symbol("MCL", dt) == "MCLJ26"

    def test_non_quarterly_december_rollover(self):
        dt = datetime(2026, 12, 1)
        # next_month = 1, year + 1 = 27, code = F
        assert get_front_month_symbol("MCL", dt) == "MCLF27"


class TestAggregateTo2Min:
    def test_basic_aggregation(self):
        bars = [
            {"timestamp": 1, "open": 100, "high": 105, "low": 99, "close": 103, "volume": 50},
            {"timestamp": 2, "open": 103, "high": 108, "low": 101, "close": 106, "volume": 60},
            {"timestamp": 3, "open": 106, "high": 110, "low": 104, "close": 109, "volume": 40},
            {"timestamp": 4, "open": 109, "high": 112, "low": 107, "close": 111, "volume": 55},
        ]
        result = aggregate_to_2min(bars)
        assert len(result) == 2

        # First 2-min bar
        assert result[0]["timestamp"] == 1
        assert result[0]["open"] == 100
        assert result[0]["high"] == 108  # max(105, 108)
        assert result[0]["low"] == 99    # min(99, 101)
        assert result[0]["close"] == 106
        assert result[0]["volume"] == 110

    def test_odd_number_of_bars(self):
        bars = [
            {"timestamp": 1, "open": 100, "high": 105, "low": 99, "close": 103, "volume": 50},
            {"timestamp": 2, "open": 103, "high": 108, "low": 101, "close": 106, "volume": 60},
            {"timestamp": 3, "open": 106, "high": 110, "low": 104, "close": 109, "volume": 40},
        ]
        result = aggregate_to_2min(bars)
        assert len(result) == 1  # Last bar dropped (odd)

    def test_empty_input(self):
        assert aggregate_to_2min([]) == []


class TestParseBars:
    def test_parse_list_format(self):
        data = [
            {"time": 1000, "open": "100", "high": "105", "low": "99", "close": "103", "volume": "50"},
            {"timestamp": 2000, "open": "200", "high": "205", "low": "199", "close": "203", "vol": "60"},
        ]
        bars = WebullBroker._parse_bars(data)
        assert len(bars) == 2
        assert bars[0]["timestamp"] == 1000
        assert bars[0]["open"] == 100.0
        assert bars[1]["timestamp"] == 2000
        assert bars[1]["volume"] == 60.0

    def test_parse_dict_with_data_key(self):
        data = {"data": [
            {"time": 1000, "open": "100", "high": "105", "low": "99", "close": "103", "volume": "50"},
        ]}
        bars = WebullBroker._parse_bars(data)
        assert len(bars) == 1

    def test_parse_empty(self):
        assert WebullBroker._parse_bars([]) == []
        assert WebullBroker._parse_bars({}) == []
        assert WebullBroker._parse_bars("invalid") == []
