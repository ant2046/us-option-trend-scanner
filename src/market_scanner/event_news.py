from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Callable

import requests
import yfinance as yf

from .models import DimensionStatus, Evidence, ProviderResult, RiskLevel, RiskTag


DEFAULT_MACRO_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
NEGATIVE_KEYWORDS = ("investigation", "lawsuit", "fraud", "recall", "downgrade", "probe")


class MacroCalendar:
    def __init__(self, *, session=None, local_path: str | Path | None = None, url: str | None = None):
        self.session = session or requests.Session()
        self.local_path = Path(local_path or Path(__file__).parents[2] / "data" / "macro_events.json")
        self.url = url or os.getenv("MACRO_CALENDAR_URL") or DEFAULT_MACRO_URL

    def events_for(self, now: datetime) -> ProviderResult:
        tags: list[RiskTag] = []
        source = "macro-online"
        try:
            response = self.session.get(self.url, timeout=10)
            response.raise_for_status()
            events = response.json()
            valid_through = None
            status = DimensionStatus.OK
        except Exception:
            source = "macro-local"
            payload = json.loads(self.local_path.read_text(encoding="utf-8"))
            events = payload.get("events", [])
            valid_through = date.fromisoformat(payload["valid_through"])
            status = DimensionStatus.OK
            if valid_through < now.date():
                status = DimensionStatus.PARTIAL
                tags.append(RiskTag(RiskLevel.CAUTION, "macro_calendar_stale", "宏观日历可能已过期", f"有效至 {valid_through}"))
        today = now.date().isoformat()
        relevant = []
        for item in events if isinstance(events, list) else []:
            raw_date = str(item.get("date") or item.get("datetime") or "")[:10]
            country = str(item.get("country") or item.get("currency") or "").upper()
            impact = str(item.get("impact") or "").lower()
            if raw_date == today and (not country or country in {"USD", "US"}) and impact in {"high", "holiday"}:
                relevant.append(str(item.get("title") or item.get("name") or "重要宏观事件"))
        evidence = (Evidence("macro_events", tuple(relevant), "；".join(relevant) if relevant else "当日无已知高影响事件", source, now),)
        if relevant:
            tags.append(RiskTag(RiskLevel.HIGH, "macro_event_day", "重大宏观事件日", "；".join(relevant[:2])))
        return ProviderResult("event_news", status, evidence, tuple(tags))


class YahooEventNewsProvider:
    def __init__(self, *, ticker_factory: Callable[[str], object] = yf.Ticker, macro_calendar: MacroCalendar | None = None):
        self.ticker_factory = ticker_factory
        self.macro_calendar = macro_calendar or MacroCalendar()

    @staticmethod
    def _earnings_date(calendar) -> datetime | None:
        if not isinstance(calendar, dict):
            return None
        value = calendar.get("Earnings Date")
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if value is None:
            return None
        stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        return stamp

    def assess(self, symbol: str, now: datetime) -> ProviderResult:
        ticker = self.ticker_factory(symbol)
        macro = self.macro_calendar.events_for(now)
        evidence = list(macro.evidence)
        tags = list(macro.tags)
        earnings = self._earnings_date(getattr(ticker, "calendar", {}))
        if earnings is not None:
            if earnings.tzinfo is None:
                earnings = earnings.replace(tzinfo=now.tzinfo)
            days = (earnings.date() - now.date()).days
            evidence.append(Evidence("earnings_days", days, f"距财报 {days} 天", "yahoo", now))
            if 0 <= days <= 3:
                tags.append(RiskTag(RiskLevel.HIGH, "earnings_soon", "3天内财报", f"预计 {earnings.date()}"))
        else:
            evidence.append(Evidence("earnings_days", None, "财报日期暂缺", "yahoo", now))
        seen: set[str] = set()
        negative: list[str] = []
        for item in getattr(ticker, "news", []) or []:
            content = item.get("content", item)
            title = str(content.get("title") or "").strip()
            if not title or title.casefold() in seen:
                continue
            seen.add(title.casefold())
            if any(keyword in title.casefold() for keyword in NEGATIVE_KEYWORDS):
                negative.append(title)
        evidence.append(Evidence("negative_headlines", tuple(negative), "；".join(negative[:2]) if negative else "未发现规则命中的负面标题", "yahoo-news", now))
        if negative:
            tags.append(RiskTag(RiskLevel.CAUTION, "negative_news", "近期负面标题", negative[0]))
        status = macro.status if earnings is not None else DimensionStatus.PARTIAL
        return ProviderResult("event_news", status, tuple(evidence), tuple(tags))
