"""Build earnings.ics from merged multi-source data."""
from __future__ import annotations

import argparse
import hashlib
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sources import (
    EarningEvent,
    FinnhubSource,
    NasdaqSource,
    YFinanceSource,
    merge_events,
)

logger = logging.getLogger(__name__)


def load_watchlist(path: Path) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        t = line.split("#", 1)[0].strip().upper()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def fetch_all(watchlist: list[str]) -> list[EarningEvent]:
    tset = set(watchlist)
    events: list[EarningEvent] = []

    yf = YFinanceSource()
    for t in watchlist:
        events.extend(yf.fetch(t))

    events.extend(NasdaqSource().fetch_range(tset, days=60))
    events.extend(FinnhubSource().fetch_range(tset, days=90))

    return merge_events(events)


# --- ICS builder ------------------------------------------------------------

def _escape(s: str) -> str:
    return (s.replace("\\", "\\\\")
             .replace(";", "\\;")
             .replace(",", "\\,")
             .replace("\n", "\\n"))


def _fold(line: str) -> str:
    """RFC 5545: long lines must be folded at 75 octets."""
    if len(line) <= 75:
        return line
    parts = [line[:75]]
    rest = line[75:]
    while rest:
        parts.append(" " + rest[:74])
        rest = rest[74:]
    return "\r\n".join(parts)


TIME_BLOCK = {  # label -> (start local, end local)
    "BMO": ("07:00", "08:00"),
    "AMC": ("16:30", "17:30"),
}


def event_to_lines(ev: EarningEvent, stamp_utc: datetime) -> list[str]:
    uid_src = f"{ev.ticker}-{ev.event_date.isoformat()}"
    uid = hashlib.md5(uid_src.encode()).hexdigest()[:16] + "@earnings-ics"
    tag = ev.time_hint if ev.time_hint in ("BMO", "AMC") else None

    summary_parts = [ev.ticker]
    if tag:
        summary_parts.append(tag)
    if ev.eps_estimate is not None:
        summary_parts.append(f"EPS est {ev.eps_estimate:.2f}")
    summary = " \u00B7 ".join(summary_parts)

    desc_lines = []
    if ev.company_name:
        desc_lines.append(ev.company_name)
    if ev.fiscal_period:
        desc_lines.append(f"Period: {ev.fiscal_period}")
    if ev.eps_estimate is not None:
        desc_lines.append(f"EPS consensus: {ev.eps_estimate:.4f}")
    if ev.eps_actual is not None:
        desc_lines.append(f"EPS actual: {ev.eps_actual:.4f}")
    if ev.revenue_estimate is not None:
        desc_lines.append(f"Revenue est: {ev.revenue_estimate:,.0f}")
    desc_lines.append(f"Time: {ev.time_hint or 'TBD'}")
    desc_lines.append(f"Sources: {', '.join(ev.sources) or 'none'}")
    description = _escape("\n".join(desc_lines))

    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp_utc.strftime('%Y%m%dT%H%M%SZ')}",
        f"SUMMARY:{_escape(summary)}",
        f"DESCRIPTION:{description}",
        "TRANSP:TRANSPARENT",
    ]

    if tag:
        sh, sm = map(int, TIME_BLOCK[tag][0].split(":"))
        eh, em = map(int, TIME_BLOCK[tag][1].split(":"))
        d = ev.event_date
        start = datetime(d.year, d.month, d.day, sh, sm)
        end = datetime(d.year, d.month, d.day, eh, em)
        lines.append(f"DTSTART;TZID=America/New_York:{start.strftime('%Y%m%dT%H%M%S')}")
        lines.append(f"DTEND;TZID=America/New_York:{end.strftime('%Y%m%dT%H%M%S')}")
    else:
        lines.append(f"DTSTART;VALUE=DATE:{ev.event_date.strftime('%Y%m%d')}")
        lines.append(
            f"DTEND;VALUE=DATE:{(ev.event_date + timedelta(days=1)).strftime('%Y%m%d')}"
        )
    lines.append("END:VEVENT")
    return lines


NY_VTIMEZONE = [
    "BEGIN:VTIMEZONE",
    "TZID:America/New_York",
    "BEGIN:STANDARD",
    "DTSTART:19701101T020000",
    "TZOFFSETFROM:-0400",
    "TZOFFSETTO:-0500",
    "TZNAME:EST",
    "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU",
    "END:STANDARD",
    "BEGIN:DAYLIGHT",
    "DTSTART:19700308T020000",
    "TZOFFSETFROM:-0500",
    "TZOFFSETTO:-0400",
    "TZNAME:EDT",
    "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU",
    "END:DAYLIGHT",
    "END:VTIMEZONE",
]


def build_ics(events: list[EarningEvent], calendar_name: str = "US Earnings") -> str:
    now = datetime.now(timezone.utc)
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//earnings-ics//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(calendar_name)}",
        "X-WR-TIMEZONE:America/New_York",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]
    lines.extend(NY_VTIMEZONE)
    for ev in events:
        lines.extend(event_to_lines(ev, now))
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"


# --- Entry point ------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--watchlist", default="watchlist.txt")
    parser.add_argument("--output", default="earnings.ics")
    parser.add_argument("--name", default="US Earnings")
    args = parser.parse_args()

    root = Path(__file__).parent
    tickers = load_watchlist(root / args.watchlist)
    logger.info("Watchlist (%d): %s", len(tickers), ", ".join(tickers))

    events = fetch_all(tickers)
    logger.info("Merged %d events", len(events))
    for ev in events:
        eps = f"{ev.eps_estimate:.2f}" if ev.eps_estimate is not None else "-"
        logger.info(
            "  %s %-6s %-3s eps=%-6s sources=%s",
            ev.event_date, ev.ticker, ev.time_hint or "TNS",
            eps, ",".join(ev.sources),
        )

    ics_text = build_ics(events, calendar_name=args.name)
    out = root / args.output
    out.write_text(ics_text, encoding="utf-8")
    logger.info("Wrote %s (%d events)", out, len(events))


if __name__ == "__main__":
    main()
