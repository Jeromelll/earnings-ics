"""Tests for merge_events: dedup, source coalescing, BMO/AMC > TNS precedence."""
from datetime import date

from sources import EarningEvent, merge_events


def _ev(ticker="AAPL", d=date(2026, 5, 1), **kw) -> EarningEvent:
    return EarningEvent(ticker=ticker, event_date=d, **kw)


class TestMerge:
    def test_empty(self):
        assert merge_events([]) == []

    def test_single_event_passes_through(self):
        ev = _ev(time_hint="BMO", sources=["nasdaq"])
        out = merge_events([ev])
        assert len(out) == 1
        assert out[0].ticker == "AAPL"

    def test_distinct_keys_not_merged(self):
        a = _ev("AAPL", date(2026, 5, 1), sources=["nasdaq"])
        b = _ev("MSFT", date(2026, 5, 1), sources=["nasdaq"])
        c = _ev("AAPL", date(2026, 5, 2), sources=["nasdaq"])
        out = merge_events([a, b, c])
        assert len(out) == 3

    def test_same_key_collapses(self):
        a = _ev(sources=["nasdaq"], time_hint="BMO")
        b = _ev(sources=["finnhub"], time_hint="BMO")
        out = merge_events([a, b])
        assert len(out) == 1
        assert sorted(out[0].sources) == ["finnhub", "nasdaq"]

    def test_bmo_overrides_tns_when_tns_first(self):
        first = _ev(sources=["nasdaq"], time_hint="TNS")
        second = _ev(sources=["finnhub"], time_hint="BMO")
        out = merge_events([first, second])
        assert out[0].time_hint == "BMO"

    def test_amc_overrides_tns_when_tns_first(self):
        first = _ev(sources=["nasdaq"], time_hint="TNS")
        second = _ev(sources=["finnhub"], time_hint="AMC")
        out = merge_events([first, second])
        assert out[0].time_hint == "AMC"

    def test_bmo_not_overridden_by_tns(self):
        # Once we have a real hint, a later TNS must NOT downgrade it.
        first = _ev(sources=["nasdaq"], time_hint="BMO")
        second = _ev(sources=["finnhub"], time_hint="TNS")
        out = merge_events([first, second])
        assert out[0].time_hint == "BMO"

    def test_none_filled_from_later(self):
        first = _ev(sources=["nasdaq"], time_hint=None)
        second = _ev(sources=["finnhub"], time_hint="AMC")
        out = merge_events([first, second])
        assert out[0].time_hint == "AMC"

    def test_missing_fields_filled_from_later(self):
        first = _ev(sources=["nasdaq"], eps_estimate=None, company_name=None)
        second = _ev(
            sources=["finnhub"],
            eps_estimate=1.5,
            company_name="Apple Inc.",
            revenue_estimate=1_000_000.0,
        )
        out = merge_events([first, second])
        assert out[0].eps_estimate == 1.5
        assert out[0].company_name == "Apple Inc."
        assert out[0].revenue_estimate == 1_000_000.0

    def test_existing_fields_not_overwritten(self):
        first = _ev(sources=["nasdaq"], eps_estimate=1.0)
        second = _ev(sources=["finnhub"], eps_estimate=2.0)
        out = merge_events([first, second])
        assert out[0].eps_estimate == 1.0  # first writer wins

    def test_duplicate_source_not_repeated(self):
        a = _ev(sources=["nasdaq"])
        b = _ev(sources=["nasdaq"])
        out = merge_events([a, b])
        assert out[0].sources == ["nasdaq"]

    def test_output_sorted_by_date_then_ticker(self):
        events = [
            _ev("MSFT", date(2026, 5, 1), sources=["nasdaq"]),
            _ev("AAPL", date(2026, 5, 1), sources=["nasdaq"]),
            _ev("AAPL", date(2026, 4, 30), sources=["nasdaq"]),
        ]
        out = merge_events(events)
        assert [(e.ticker, e.event_date) for e in out] == [
            ("AAPL", date(2026, 4, 30)),
            ("AAPL", date(2026, 5, 1)),
            ("MSFT", date(2026, 5, 1)),
        ]

    def test_three_way_merge(self):
        a = _ev(sources=["yfinance"], time_hint="TNS", eps_estimate=None)
        b = _ev(sources=["nasdaq"], time_hint="TNS", eps_estimate=1.5)
        c = _ev(sources=["finnhub"], time_hint="AMC", company_name="Apple Inc.")
        out = merge_events([a, b, c])
        assert len(out) == 1
        merged = out[0]
        assert sorted(merged.sources) == ["finnhub", "nasdaq", "yfinance"]
        assert merged.time_hint == "AMC"
        assert merged.eps_estimate == 1.5
        assert merged.company_name == "Apple Inc."
