"""Multi-source earnings fetchers. Each adapter is independent so one failing
source never blocks the others."""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable

logger = logging.getLogger(__name__)


@dataclass
class EarningEvent:
    ticker: str
    event_date: date
    time_hint: str | None = None          # "BMO" | "AMC" | "TNS" | "HH:MM"
    eps_estimate: float | None = None
    eps_actual: float | None = None
    revenue_estimate: float | None = None
    fiscal_period: str | None = None
    company_name: str | None = None
    sources: list[str] = field(default_factory=list)

    def key(self) -> tuple[str, date]:
        return (self.ticker.upper(), self.event_date)


def _to_float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (ValueError, TypeError):
        return None
    if f != f:  # NaN
        return None
    return f


def _parse_money(v) -> float | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s or s in {"N/A", "--", ""}:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("$", "").replace(",", "")
    try:
        f = float(s)
    except ValueError:
        return None
    return -f if neg else f


def _classify_hour(dt: datetime) -> str:
    """Convert a US/Eastern datetime into BMO/AMC/TNS/HH:MM tag."""
    if dt.hour == 0 and dt.minute == 0:
        return "TNS"
    if dt.hour < 9 or (dt.hour == 9 and dt.minute < 30):
        return "BMO"
    if dt.hour >= 16:
        return "AMC"
    return dt.strftime("%H:%M")


# --- Source 1: yfinance (per ticker, no API key) -----------------------------

class YFinanceSource:
    name = "yfinance"

    def fetch(self, ticker: str) -> list[EarningEvent]:
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance not installed")
            return []

        try:
            t = yf.Ticker(ticker)
            df = t.get_earnings_dates(limit=12)
        except Exception as e:
            logger.warning("yfinance get_earnings_dates %s: %s", ticker, e)
            return []
        if df is None or df.empty:
            return []

        try:
            info = t.info or {}
            name = info.get("shortName") or info.get("longName")
        except Exception:
            name = None

        events: list[EarningEvent] = []
        cutoff = date.today() - timedelta(days=3)
        for idx, row in df.iterrows():
            try:
                dt = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx
                if dt.date() < cutoff:
                    continue
                events.append(EarningEvent(
                    ticker=ticker.upper(),
                    event_date=dt.date(),
                    time_hint=_classify_hour(dt),
                    eps_estimate=_to_float(row.get("EPS Estimate")),
                    eps_actual=_to_float(row.get("Reported EPS")),
                    company_name=name,
                    sources=[self.name],
                ))
            except Exception as e:
                logger.debug("yf row parse fail %s: %s", ticker, e)
        return events


# --- Source 2: Nasdaq public calendar (date-range, no API key) ---------------

class NasdaqSource:
    name = "nasdaq"
    BASE = "https://api.nasdaq.com/api"
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://www.nasdaq.com",
        "Referer": "https://www.nasdaq.com/",
    }

    def fetch_range(self, tickers: set[str], days: int = 60) -> list[EarningEvent]:
        import requests
        events: list[EarningEvent] = []
        upper = {t.upper() for t in tickers}
        today = date.today()
        for offset in range(days):
            d = today + timedelta(days=offset)
            url = f"{self.BASE}/calendar/earnings?date={d.isoformat()}"
            try:
                r = requests.get(url, headers=self.HEADERS, timeout=15)
                if r.status_code != 200:
                    continue
                data = r.json()
            except Exception as e:
                logger.debug("nasdaq %s: %s", d, e)
                continue
            payload = (data or {}).get("data") or {}
            rows = payload.get("rows") or []
            for row in rows:
                sym = (row.get("symbol") or "").upper()
                if sym not in upper:
                    continue
                raw = (row.get("time") or "").lower()
                if "pre" in raw or "before" in raw:
                    hint = "BMO"
                elif "after" in raw or "post" in raw:
                    hint = "AMC"
                else:
                    hint = "TNS"
                events.append(EarningEvent(
                    ticker=sym,
                    event_date=d,
                    time_hint=hint,
                    eps_estimate=_parse_money(row.get("epsForecast")),
                    fiscal_period=row.get("fiscalQuarterEnding") or None,
                    company_name=row.get("name") or None,
                    sources=[self.name],
                ))
            time.sleep(0.25)  # be polite
        return events


# --- Source 3: Finnhub (range + consensus, requires free API key) ------------

class FinnhubSource:
    name = "finnhub"
    BASE = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("FINNHUB_API_KEY")

    def fetch_range(self, tickers: set[str], days: int = 90) -> list[EarningEvent]:
        if not self.api_key:
            logger.info("FINNHUB_API_KEY not set, skipping finnhub")
            return []
        import requests
        today = date.today()
        params = {
            "from": today.isoformat(),
            "to": (today + timedelta(days=days)).isoformat(),
            "token": self.api_key,
        }
        try:
            r = requests.get(f"{self.BASE}/calendar/earnings",
                             params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.warning("finnhub fetch failed: %s", e)
            return []

        events: list[EarningEvent] = []
        upper = {t.upper() for t in tickers}
        for row in (data or {}).get("earningsCalendar", []) or []:
            sym = (row.get("symbol") or "").upper()
            if sym not in upper:
                continue
            try:
                d = date.fromisoformat(row["date"])
            except Exception:
                continue
            h = (row.get("hour") or "").lower()
            hint = "BMO" if h == "bmo" else "AMC" if h == "amc" else "TNS"
            q, y = row.get("quarter"), row.get("year")
            period = f"Q{q} {y}" if q and y else None
            events.append(EarningEvent(
                ticker=sym,
                event_date=d,
                time_hint=hint,
                eps_estimate=_to_float(row.get("epsEstimate")),
                eps_actual=_to_float(row.get("epsActual")),
                revenue_estimate=_to_float(row.get("revenueEstimate")),
                fiscal_period=period,
                sources=[self.name],
            ))
        return events


# --- Merge ------------------------------------------------------------------

_FIELDS_FILLABLE = (
    "eps_estimate", "eps_actual", "revenue_estimate",
    "fiscal_period", "company_name",
)


def merge_events(all_events: Iterable[EarningEvent]) -> list[EarningEvent]:
    """Collapse events that share (ticker, date). Sources append; missing fields
    fill from later records. BMO/AMC always wins over TNS."""
    by_key: dict[tuple[str, date], EarningEvent] = {}
    for ev in all_events:
        k = ev.key()
        if k not in by_key:
            by_key[k] = ev
            continue
        cur = by_key[k]
        for s in ev.sources:
            if s not in cur.sources:
                cur.sources.append(s)
        if cur.time_hint in (None, "TNS") and ev.time_hint not in (None, "TNS"):
            cur.time_hint = ev.time_hint
        for fld in _FIELDS_FILLABLE:
            if getattr(cur, fld) is None and getattr(ev, fld) is not None:
                setattr(cur, fld, getattr(ev, fld))
    return sorted(by_key.values(), key=lambda e: (e.event_date, e.ticker))
