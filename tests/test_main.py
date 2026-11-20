from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from market_scanner.config import Settings
from market_scanner.data import FallbackMarketData, YahooMarketData
from market_scanner.event_news import FallbackEventNewsProvider, YahooEventNewsProvider
from market_scanner.main import Dependencies, RunStatus, _dependencies, run_scan
from market_scanner.massive_data import MassiveMarketData
from market_scanner.options import YahooOptionsProvider
from market_scanner.providers import YahooFundamentalsProvider
from market_scanner.models import DimensionStatus, EnrichmentBundle, MarketSession, PremarketQuote, ProviderResult, QuoteStatus, TrendSignal
from market_scanner.scoring import AssessmentScorer


NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 19, 8, 30, tzinfo=NY)


class FakeCalendar:
    def __init__(self, opened=True):
        self.opened = opened

    def session_for(self, value):
        return MarketSession(value, value_to_open(value)) if self.opened else None


def value_to_open(value):
    return datetime(value.year, value.month, value.day, 9, 30, tzinfo=NY)


class FakeData:
    def __init__(self, failing=()):
        self.failing = set(failing)
        self.daily_calls = []

    def daily_history(self, symbol, completed_before):
        self.daily_calls.append(symbol)
        if symbol in self.failing:
            raise RuntimeError("failed")
        return pd.DataFrame({"symbol": [symbol]})

    def premarket_quote(self, symbol, now):
        return PremarketQuote(symbol, QuoteStatus.OK, 101, now)


class FakeSignals:
    def trend_qualifies(self, bars):
        return True

    def evaluate(self, symbol, bars, qqq_trend_ok):
        return TrendSignal(symbol, date(2026, 11, 18), 100, 95, 90, 4, ("平台突破",), 92)


class Sender:
    def __init__(self, fail=False):
        self.messages = []
        self.images = []
        self.fail = fail

    def send(self, message):
        if self.fail:
            raise RuntimeError("send failed")
        self.messages.append(message)

    def send_image(self, image_bytes):
        if self.fail:
            raise RuntimeError("send failed")
        self.images.append(image_bytes)


def deps(data=None, opened=True, sender=None, output=None):
    sender = sender or Sender()
    return Dependencies(FakeCalendar(opened), data or FakeData(), FakeSignals(), lambda: sender, output or (lambda _: None))


def test_closed_market_skips_data_and_send():
    data = FakeData()
    sender = Sender()
    result = run_scan(deps(data, opened=False, sender=sender), now=NOW, send=True)
    assert result.status == RunStatus.SKIPPED_MARKET_CLOSED
    assert data.daily_calls == []
    assert sender.messages == []


def test_normal_flow_fetches_qqq_first_and_sends_one_png():
    data = FakeData()
    sender = Sender()
    result = run_scan(deps(data, sender=sender), now=NOW, send=True)
    assert result.status == RunStatus.SUCCESS
    assert data.daily_calls[0] == "QQQ"
    assert sender.messages == []
    assert len(sender.images) == 1
    assert sender.images[0].startswith(b"\x89PNG\r\n\x1a\n")


def test_one_symbol_failure_is_listed_but_scan_succeeds():
    sender = Sender()
    result = run_scan(deps(FakeData(failing=("TSLA",)), sender=sender), now=NOW, send=True)
    assert result.status == RunStatus.SUCCESS
    assert len(sender.images) == 1


def test_all_daily_failures_return_data_failed():
    data = FakeData(failing=("SPY", "QQQ", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"))
    result = run_scan(deps(data), now=NOW, send=False)
    assert result.status == RunStatus.DATA_FAILED


def test_dry_run_prints_without_constructing_sender():
    output = []
    dependencies = Dependencies(FakeCalendar(), FakeData(), FakeSignals(), lambda: (_ for _ in ()).throw(AssertionError("sender constructed")), output.append)
    result = run_scan(dependencies, now=NOW, send=False)
    assert result.status == RunStatus.SUCCESS
    assert output and "美股盘前趋势扫描" in output[0]


def test_send_failure_returns_delivery_failed():
    result = run_scan(deps(sender=Sender(fail=True)), now=NOW, send=True)
    assert result.status == RunStatus.DELIVERY_FAILED


def test_image_render_failure_returns_delivery_failed(monkeypatch):
    def fail_render(report):
        raise RuntimeError("render failed")

    monkeypatch.setattr("market_scanner.main.render_png", fail_render)

    assert run_scan(deps(), now=NOW, send=True).status == RunStatus.DELIVERY_FAILED


def test_qqq_trend_bonus_does_not_require_qqq_trigger():
    class TrendOnlyQQQ(FakeSignals):
        def evaluate(self, symbol, bars, qqq_trend_ok):
            if symbol == "QQQ":
                return None
            assert qqq_trend_ok is True
            return super().evaluate(symbol, bars, qqq_trend_ok)

    dependencies = Dependencies(FakeCalendar(), FakeData(), TrendOnlyQQQ(), lambda: Sender(), lambda _: None)
    assert run_scan(dependencies, now=NOW, send=False).status == RunStatus.SUCCESS


def test_report_separates_benchmark_trend_from_trigger_and_lists_quote_anomalies(monkeypatch):
    captured = []

    class TrendOnlyQQQ(FakeSignals):
        def evaluate(self, symbol, bars, qqq_trend_ok):
            if symbol == "QQQ":
                return None
            return super().evaluate(symbol, bars, qqq_trend_ok)

    class StaleData(FakeData):
        def premarket_quote(self, symbol, now):
            if symbol == "TSLA":
                return PremarketQuote(symbol, QuoteStatus.STALE, 99, now)
            return super().premarket_quote(symbol, now)

    def capture(report):
        captured.append(report)
        return b"png"

    monkeypatch.setattr("market_scanner.main.render_png", capture)
    dependencies = Dependencies(FakeCalendar(), StaleData(), TrendOnlyQQQ(), lambda: Sender(), lambda _: None)

    assert run_scan(dependencies, now=NOW, send=True).status == RunStatus.SUCCESS
    assert captured[0].qqq_summary == "QQQ 趋势合格"
    assert "TSLA" in captured[0].failures


def test_all_daily_failures_report_market_data_unavailable(monkeypatch):
    captured = []
    monkeypatch.setattr("market_scanner.main.render_png", lambda report: captured.append(report) or b"png")
    data = FakeData(failing=("SPY", "QQQ", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"))

    assert run_scan(deps(data), now=NOW, send=True).status == RunStatus.DATA_FAILED
    assert captured[0].spy_summary == "SPY 数据异常"
    assert captured[0].qqq_summary == "QQQ 数据异常"


class FakeEnricher:
    def __init__(self, *, failed=False):
        self.contexts = ()
        self.failed = failed

    def enrich(self, contexts):
        self.contexts = contexts
        status = DimensionStatus.ERROR if self.failed else DimensionStatus.UNAVAILABLE
        return {
            item.symbol: EnrichmentBundle(
                market=ProviderResult("market", status),
                fundamental=ProviderResult("fundamental", status),
                event_news=ProviderResult("event_news", status),
                options=ProviderResult("options", status),
            )
            for item in contexts
        }


def test_enrichment_only_receives_candidates_and_preserves_original_order(monkeypatch):
    captured = []
    enricher = FakeEnricher()
    monkeypatch.setattr("market_scanner.main.render_png_pages", lambda report: captured.append(report) or (b"page-1", b"page-2"))
    sender = Sender()
    dependencies = deps(sender=sender)
    dependencies = Dependencies(
        dependencies.calendar, dependencies.data, dependencies.signals, dependencies.sender_factory,
        dependencies.output, dependencies.settings, enricher, AssessmentScorer(),
    )

    result = run_scan(dependencies, now=NOW, send=True)

    expected = ("AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "QQQ", "SPY", "TSLA")
    assert tuple(item.symbol for item in enricher.contexts) == expected
    assert tuple(item.candidate.signal.symbol for item in captured[0].assessments) == expected
    assert sender.images == [b"page-1", b"page-2"]
    assert result.enrichment_failure_count == 0


def test_all_enrichment_failures_still_deliver_and_are_counted(monkeypatch):
    enricher = FakeEnricher(failed=True)
    monkeypatch.setattr("market_scanner.main.render_png_pages", lambda report: (b"technical-report",))
    sender = Sender()
    base = deps(sender=sender)
    dependencies = Dependencies(
        base.calendar, base.data, base.signals, base.sender_factory, base.output, base.settings,
        enricher, AssessmentScorer(),
    )

    result = run_scan(dependencies, now=NOW, send=True)

    assert result.status == RunStatus.SUCCESS
    assert result.enrichment_failure_count == 9
    assert sender.images == [b"technical-report"]


def test_scoring_failure_for_one_candidate_does_not_block_delivery(monkeypatch):
    class BrokenScorer:
        def score(self, candidate, bundle):
            raise TypeError("malformed provider value")

    monkeypatch.setattr("market_scanner.main.render_png", lambda report: b"technical-fallback")
    sender = Sender()
    base = deps(sender=sender)
    dependencies = Dependencies(base.calendar, base.data, base.signals, base.sender_factory, base.output, base.settings, FakeEnricher(), BrokenScorer())

    result = run_scan(dependencies, now=NOW, send=True)

    assert result.status == RunStatus.SUCCESS
    assert result.enrichment_failure_count == 9
    assert sender.images == [b"technical-fallback"]


def test_dependency_assembly_uses_massive_primary_and_yahoo_fallback_when_configured():
    dependencies = _dependencies(Settings(massive_api_key="configured-secret"))

    assert isinstance(dependencies.data, FallbackMarketData)
    assert isinstance(dependencies.data._primary, MassiveMarketData)
    assert isinstance(dependencies.data._fallback, YahooMarketData)
    assert isinstance(dependencies.enrichment.providers["event_news"], FallbackEventNewsProvider)
    assert isinstance(dependencies.enrichment.providers["fundamental"], YahooFundamentalsProvider)
    assert isinstance(dependencies.enrichment.providers["options"], YahooOptionsProvider)
    assert "configured-secret" not in repr(dependencies.settings)


def test_dependency_assembly_remains_yahoo_only_without_massive_key():
    dependencies = _dependencies(Settings())

    assert isinstance(dependencies.data, YahooMarketData)
    assert isinstance(dependencies.enrichment.providers["event_news"], YahooEventNewsProvider)
    assert isinstance(dependencies.enrichment.providers["fundamental"], YahooFundamentalsProvider)
    assert isinstance(dependencies.enrichment.providers["options"], YahooOptionsProvider)
