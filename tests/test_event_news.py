import json
from datetime import datetime
from zoneinfo import ZoneInfo

from market_scanner.event_news import (
    FallbackEventNewsProvider,
    MacroCalendar,
    MassiveEventNewsProvider,
    YahooEventNewsProvider,
)
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
    local.write_text(json.dumps({"coverage_start": "2026-11-16", "valid_through": "2026-11-22", "events": []}), encoding="utf-8")
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
    assert result.evidence[0].value is None


def test_event_provider_ignores_old_news_and_does_not_award_unknown_freshness(tmp_path):
    class OldNewsTicker:
        calendar = {}
        news = [{"content": {"title": "Company faces investigation", "provider": {"displayName": "Wire"}, "pubDate": "2026-11-16T12:00:00Z"}}]
    local = tmp_path / "macro.json"
    local.write_text(json.dumps({"coverage_start": "2026-11-16", "valid_through": "2026-11-22", "events": []}), encoding="utf-8")
    result = YahooEventNewsProvider(ticker_factory=lambda symbol: OldNewsTicker(), macro_calendar=MacroCalendar(session=FailedSession(), local_path=local)).assess("AAPL", datetime(2026, 11, 19, 8, 30, tzinfo=NY))
    values = {item.key: item.value for item in result.evidence}
    assert values["negative_headlines"] == () and values["news_fresh"] is False
    assert "negative_news" not in {tag.code for tag in result.tags}


class MassiveClient:
    def __init__(self, results=None, error=None):
        self.results = results or []
        self.error = error

    def get(self, path, params=None, *, paginate=False):
        if self.error:
            raise self.error
        return tuple(self.results)


def valid_macro(tmp_path):
    local = tmp_path / "macro.json"
    local.write_text(json.dumps({"coverage_start": "2026-11-16", "valid_through": "2026-11-22", "events": []}), encoding="utf-8")
    return MacroCalendar(session=FailedSession(), local_path=local)


def test_massive_event_provider_maps_deduplicates_and_labels_recent_news(tmp_path):
    results = [
        {
            "title": "Company faces investigation",
            "publisher": {"name": "Wire"},
            "published_utc": "2026-11-19T12:00:00Z",
            "article_url": "https://example.test/a",
        },
        {
            "title": "Company faces investigation",
            "publisher": {"name": "Wire"},
            "published_utc": "2026-11-19T12:00:00Z",
            "article_url": "https://example.test/duplicate",
        },
        {
            "title": "Old lawsuit headline",
            "publisher": {"name": "Wire"},
            "published_utc": "2026-11-16T12:00:00Z",
            "article_url": "https://example.test/old",
        },
    ]
    provider = MassiveEventNewsProvider(
        MassiveClient(results),
        ticker_factory=lambda symbol: FakeTicker(),
        macro_calendar=valid_macro(tmp_path),
    )

    result = provider.assess("AAPL", datetime(2026, 11, 19, 8, 30, tzinfo=NY))
    values = {item.key: item for item in result.evidence}

    assert values["negative_headlines"].value == ("Company faces investigation",)
    assert values["negative_headlines"].source == "massive-news"
    assert values["news_fresh"].value is True
    assert sum(tag.code == "negative_news" for tag in result.tags) == 1
    assert sum(tag.code == "earnings_soon" for tag in result.tags) == 1


def test_massive_event_provider_treats_malformed_or_empty_news_as_unavailable(tmp_path):
    empty = MassiveEventNewsProvider(
        MassiveClient([]), ticker_factory=lambda symbol: FakeTicker(), macro_calendar=valid_macro(tmp_path)
    ).assess("AAPL", datetime(2026, 11, 19, 8, 30, tzinfo=NY))
    malformed = MassiveEventNewsProvider(
        MassiveClient([{"title": "Missing publisher and date"}]),
        ticker_factory=lambda symbol: FakeTicker(),
        macro_calendar=valid_macro(tmp_path),
    ).assess("AAPL", datetime(2026, 11, 19, 8, 30, tzinfo=NY))

    assert next(item for item in empty.evidence if item.key == "news_fresh").value is False
    assert next(item for item in malformed.evidence if item.key == "news_fresh").value is False


class ResultProvider:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    def assess(self, symbol, now):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def test_event_news_fallback_skips_yahoo_for_fresh_massive_news(tmp_path):
    massive = MassiveEventNewsProvider(
        MassiveClient([{"title": "Routine update", "publisher": {"name": "Wire"}, "published_utc": "2026-11-19T12:00:00Z"}]),
        ticker_factory=lambda symbol: FakeTicker(),
        macro_calendar=valid_macro(tmp_path),
    ).assess("AAPL", datetime(2026, 11, 19, 8, 30, tzinfo=NY))
    primary = ResultProvider(massive)
    fallback = ResultProvider(error=AssertionError("Yahoo must not be called"))

    result = FallbackEventNewsProvider(primary, fallback).assess("AAPL", datetime(2026, 11, 19, 8, 30, tzinfo=NY))

    assert result == massive
    assert fallback.calls == 0


def test_event_news_fallback_uses_yahoo_and_marks_source_when_massive_fails(tmp_path):
    yahoo = YahooEventNewsProvider(
        ticker_factory=lambda symbol: FakeTicker(), macro_calendar=valid_macro(tmp_path)
    ).assess("AAPL", datetime(2026, 11, 19, 8, 30, tzinfo=NY))
    provider = FallbackEventNewsProvider(ResultProvider(error=TimeoutError("offline")), ResultProvider(yahoo))

    result = provider.assess("AAPL", datetime(2026, 11, 19, 8, 30, tzinfo=NY))
    sources = {item.source for item in result.evidence if item.key in {"negative_headlines", "news_fresh"}}

    assert sources == {"yahoo_fallback"}
