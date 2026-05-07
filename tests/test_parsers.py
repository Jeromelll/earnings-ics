"""Tests for the small numeric/time parsers in sources.py."""
from datetime import datetime

import pytest

from sources import _classify_hour, _parse_money, _to_float


class TestToFloat:
    def test_none_returns_none(self):
        assert _to_float(None) is None

    def test_int_converts(self):
        assert _to_float(3) == 3.0

    def test_str_converts(self):
        assert _to_float("1.5") == 1.5

    def test_invalid_str_returns_none(self):
        assert _to_float("abc") is None

    def test_empty_str_returns_none(self):
        assert _to_float("") is None

    def test_nan_returns_none(self):
        assert _to_float(float("nan")) is None

    def test_negative_works(self):
        assert _to_float("-2.5") == -2.5


class TestParseMoney:
    def test_none_returns_none(self):
        assert _parse_money(None) is None

    def test_empty_returns_none(self):
        assert _parse_money("") is None

    def test_whitespace_returns_none(self):
        assert _parse_money("   ") is None

    @pytest.mark.parametrize("v", ["N/A", "--"])
    def test_sentinel_strings_return_none(self, v):
        assert _parse_money(v) is None

    def test_plain_number(self):
        assert _parse_money("1.50") == 1.5

    def test_strips_dollar_sign(self):
        assert _parse_money("$1.50") == 1.5

    def test_strips_commas(self):
        assert _parse_money("1,234.56") == 1234.56

    def test_dollar_and_commas(self):
        assert _parse_money("$1,234,567.89") == 1234567.89

    def test_parentheses_mean_negative(self):
        assert _parse_money("(1.50)") == -1.5

    def test_parentheses_with_dollar(self):
        assert _parse_money("($1,234.56)") == -1234.56

    def test_invalid_returns_none(self):
        assert _parse_money("abc") is None


class TestClassifyHour:
    def test_midnight_means_tns(self):
        # Midnight is the conventional "no time information" sentinel.
        assert _classify_hour(datetime(2026, 5, 1, 0, 0)) == "TNS"

    def test_early_morning_is_bmo(self):
        assert _classify_hour(datetime(2026, 5, 1, 7, 0)) == "BMO"

    def test_just_before_open_is_bmo(self):
        assert _classify_hour(datetime(2026, 5, 1, 9, 29)) == "BMO"

    def test_market_open_is_intraday(self):
        # 09:30 onward is no longer pre-market.
        assert _classify_hour(datetime(2026, 5, 1, 9, 30)) == "09:30"

    def test_intraday_returns_hhmm(self):
        assert _classify_hour(datetime(2026, 5, 1, 12, 15)) == "12:15"

    def test_close_is_amc(self):
        assert _classify_hour(datetime(2026, 5, 1, 16, 0)) == "AMC"

    def test_late_evening_is_amc(self):
        assert _classify_hour(datetime(2026, 5, 1, 20, 30)) == "AMC"

    def test_one_minute_past_midnight_is_bmo_not_tns(self):
        # The TNS sentinel is exactly 00:00; 00:01 should classify as BMO.
        assert _classify_hour(datetime(2026, 5, 1, 0, 1)) == "BMO"
