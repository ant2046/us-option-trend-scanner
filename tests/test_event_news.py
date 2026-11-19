import json
from datetime import datetime
from zoneinfo import ZoneInfo

from market_scanner.event_news import MacroCalendar, YahooEventNewsProvider
from market_scanner.models import DimensionStatus, RiskLevel


NY = ZoneInfo("America/New_York")


class FailedSession:
    def get(self, *args, **kwargs):
        raise TimeoutError("offline")


class FakeTicker:
    calendar = {"Earnings Date": [datetime(2026, 11, 21, tzinfo=NY)]}
    news = [
        {"content": {"title": "Company faces investigation", "provider": {"displayName": "Wire"}, "pubDate": "2026-11-19T12:00:00Z"}},
        {"content": {"title": "Company faces investigation", "provider": {"displayName": "Wire"}, "pubDate": "2026-11-19T12:00:00Z"}},
    ]


def test_event_provider_labels_near_earnings_and_deduplicated_negative_news(tmp_path):
    local = tmp_path / "macro.json"
    local.write_text(json.dumps({"valid_through": "2026-12-31", "events": []}), encoding="utf-8")
    provider = YahooEventNewsProvider(
        ticker_factory=lambda symbol: FakeTicker(),
        macro_calendar=MacroCalendar(session=FailedSession(), local_path=local),
    )

    result = provider.assess("AAPL", datetime(2026, 11, 19, 8, 30, tzinfo=NY))

    assert result.status == DimensionStatus.OK
    assert sum(tag.code == "earnings_soon" for tag in result.tags) == 1
    assert next(tag for tag in result.tags if tag.code == "earnings_soon").level == RiskLevel.HIGH
    assert sum(tag.code == "negative_news" for tag in result.tags) == 1
    assert next(tag for tag in result.tags if tag.code == "negative_news").level == RiskLevel.CAUTION


def test_stale_local_macro_calendar_warns_instead_of_claiming_clean(tmp_path):
    local = tmp_path / "macro.json"
    local.write_text(json.dumps({"valid_through": "2026-01-01", "events": []}), encoding="utf-8")

    result = MacroCalendar(session=FailedSession(), local_path=local).events_for(datetime(2026, 11, 19, tzinfo=NY))

    assert result.status == DimensionStatus.PARTIAL
    assert any(tag.code == "macro_calendar_stale" for tag in result.tags)
