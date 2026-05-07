"""RFC 5545 escaping and line-folding tests.

These functions are correctness-critical for calendar clients. A broken escape
silently corrupts SUMMARY/DESCRIPTION; a broken fold produces invalid ICS that
some clients reject and others render with literal whitespace.
"""
from datetime import date, datetime, timezone

import pytest

from main import _escape, _fold, build_ics, event_to_lines
from sources import EarningEvent


class TestEscape:
    def test_passthrough_plain_text(self):
        assert _escape("Plain text 123") == "Plain text 123"

    def test_escapes_backslash_first(self):
        # Backslash must be doubled BEFORE other rules add backslashes,
        # otherwise \; would become \\; (escaped semicolon) instead of \\\;
        assert _escape("a\\b") == "a\\\\b"

    def test_escapes_semicolon(self):
        assert _escape("a;b") == "a\\;b"

    def test_escapes_comma(self):
        assert _escape("a,b") == "a\\,b"

    def test_escapes_newline(self):
        assert _escape("line1\nline2") == "line1\\nline2"

    def test_escapes_all_specials_together(self):
        assert _escape("a\\b;c,d\ne") == "a\\\\b\\;c\\,d\\ne"

    def test_escape_order_backslash_before_others(self):
        # If backslash were escaped last, the backslashes added by ; , \n
        # would themselves get doubled.
        out = _escape(";")
        assert out == "\\;"
        assert out.count("\\") == 1


class TestFold:
    def test_short_line_unchanged(self):
        line = "X" * 75
        assert _fold(line) == line

    def test_76_char_line_folds_once(self):
        line = "X" * 76
        folded = _fold(line)
        assert folded == "X" * 75 + "\r\n " + "X"

    def test_first_segment_is_75_octets(self):
        line = "A" * 200
        folded = _fold(line)
        first = folded.split("\r\n")[0]
        assert len(first) == 75

    def test_continuation_lines_start_with_space(self):
        line = "A" * 200
        folded = _fold(line)
        for cont in folded.split("\r\n")[1:]:
            assert cont.startswith(" ")

    def test_continuation_payload_is_74_octets(self):
        # Each continuation line is " " + 74 payload chars = 75 octets total.
        line = "A" * (75 + 74 + 50)
        folded = _fold(line).split("\r\n")
        assert len(folded[0]) == 75
        assert len(folded[1]) == 75  # 1 space + 74 chars
        assert folded[2] == " " + "A" * 50

    def test_long_line_round_trips(self):
        line = "A" * 300
        folded = _fold(line)
        # Unfold by removing CRLF+space sequences as a calendar client would.
        unfolded = folded.replace("\r\n ", "")
        assert unfolded == line

    def test_exact_boundary_75_does_not_fold(self):
        line = "A" * 75
        assert "\r\n" not in _fold(line)

    def test_exact_boundary_76_does_fold(self):
        line = "A" * 76
        assert "\r\n" in _fold(line)


def _make_event(**overrides) -> EarningEvent:
    base = dict(
        ticker="AAPL",
        event_date=date(2026, 5, 1),
        time_hint="BMO",
        sources=["nasdaq"],
    )
    base.update(overrides)
    return EarningEvent(**base)


class TestEventToLines:
    def test_bmo_uses_timed_event(self):
        ev = _make_event(time_hint="BMO")
        lines = event_to_lines(ev, datetime(2026, 5, 1, tzinfo=timezone.utc))
        assert any(l.startswith("DTSTART;TZID=America/New_York:") for l in lines)
        assert any(l.startswith("DTEND;TZID=America/New_York:") for l in lines)
        assert not any(l.startswith("DTSTART;VALUE=DATE:") for l in lines)

    def test_amc_uses_timed_event(self):
        ev = _make_event(time_hint="AMC")
        lines = event_to_lines(ev, datetime(2026, 5, 1, tzinfo=timezone.utc))
        assert any("16302026" not in l for l in lines)  # sanity
        assert any(l.startswith("DTSTART;TZID=America/New_York:") for l in lines)

    def test_tns_uses_all_day_event(self):
        ev = _make_event(time_hint="TNS")
        lines = event_to_lines(ev, datetime(2026, 5, 1, tzinfo=timezone.utc))
        assert any(l.startswith("DTSTART;VALUE=DATE:20260501") for l in lines)
        assert any(l.startswith("DTEND;VALUE=DATE:20260502") for l in lines)

    def test_none_time_hint_uses_all_day(self):
        ev = _make_event(time_hint=None)
        lines = event_to_lines(ev, datetime(2026, 5, 1, tzinfo=timezone.utc))
        assert any(l.startswith("DTSTART;VALUE=DATE:") for l in lines)

    def test_uid_is_stable_for_same_ticker_and_date(self):
        ev1 = _make_event(time_hint="BMO", sources=["nasdaq"])
        ev2 = _make_event(time_hint="AMC", sources=["finnhub"])
        stamp = datetime(2026, 5, 1, tzinfo=timezone.utc)
        uid1 = next(l for l in event_to_lines(ev1, stamp) if l.startswith("UID:"))
        uid2 = next(l for l in event_to_lines(ev2, stamp) if l.startswith("UID:"))
        assert uid1 == uid2

    def test_uid_differs_when_date_differs(self):
        ev1 = _make_event(event_date=date(2026, 5, 1))
        ev2 = _make_event(event_date=date(2026, 5, 2))
        stamp = datetime(2026, 5, 1, tzinfo=timezone.utc)
        uid1 = next(l for l in event_to_lines(ev1, stamp) if l.startswith("UID:"))
        uid2 = next(l for l in event_to_lines(ev2, stamp) if l.startswith("UID:"))
        assert uid1 != uid2

    def test_summary_includes_eps_estimate(self):
        ev = _make_event(eps_estimate=1.234)
        lines = event_to_lines(ev, datetime(2026, 5, 1, tzinfo=timezone.utc))
        summary = next(l for l in lines if l.startswith("SUMMARY:"))
        assert "EPS est 1.23" in summary

    def test_description_escapes_newlines(self):
        ev = _make_event(company_name="Apple Inc.", fiscal_period="Q2 2026")
        lines = event_to_lines(ev, datetime(2026, 5, 1, tzinfo=timezone.utc))
        desc = next(l for l in lines if l.startswith("DESCRIPTION:"))
        # Description joins with \n then escapes — must contain literal "\n", not raw newline.
        assert "\\n" in desc
        assert "\n" not in desc[len("DESCRIPTION:"):]

    def test_description_escapes_special_chars_in_company_name(self):
        ev = _make_event(company_name="Foo, Bar; Baz")
        lines = event_to_lines(ev, datetime(2026, 5, 1, tzinfo=timezone.utc))
        desc = next(l for l in lines if l.startswith("DESCRIPTION:"))
        assert "\\," in desc
        assert "\\;" in desc


class TestBuildIcs:
    def test_empty_calendar_has_required_headers(self):
        out = build_ics([])
        assert out.startswith("BEGIN:VCALENDAR\r\n")
        assert out.rstrip("\r\n").endswith("END:VCALENDAR")
        assert "VERSION:2.0" in out
        assert "PRODID:" in out

    def test_includes_vtimezone(self):
        out = build_ics([])
        assert "BEGIN:VTIMEZONE" in out
        assert "TZID:America/New_York" in out
        assert "END:VTIMEZONE" in out

    def test_event_count_matches_input(self):
        events = [
            _make_event(ticker="AAPL", event_date=date(2026, 5, 1)),
            _make_event(ticker="MSFT", event_date=date(2026, 5, 2)),
        ]
        out = build_ics(events)
        assert out.count("BEGIN:VEVENT") == 2
        assert out.count("END:VEVENT") == 2

    def test_uses_crlf_line_endings(self):
        out = build_ics([_make_event()])
        # RFC 5545 mandates CRLF; bare \n would break strict parsers.
        assert "\r\n" in out
        # No bare LF outside of CRLF pairs.
        assert "\n" not in out.replace("\r\n", "")

    def test_calendar_name_escaped(self):
        out = build_ics([], calendar_name="Earnings; Foo")
        assert "X-WR-CALNAME:Earnings\\; Foo" in out
