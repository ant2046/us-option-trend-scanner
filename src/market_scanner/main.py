from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Callable
from zoneinfo import ZoneInfo

from .calendar import MarketSessionService
from .config import ConfigError, Settings, SYMBOLS
from .data import FallbackMarketData, YahooMarketData
from .enrichment import CandidateInput, EnrichmentRunner
from .event_news import FallbackEventNewsProvider, MacroCalendar, MassiveEventNewsProvider, YahooEventNewsProvider
from .image_report import render_png, render_png_pages
from .massive import MassiveClient
from .massive_data import MassiveMarketData
from .models import DimensionStatus, QuoteStatus
from .options import YahooOptionsProvider
from .premarket import evaluate_premarket, rank_candidates
from .providers import YahooFundamentalsProvider, YahooMarketContextProvider
from .report import ScanReport, WeComClient, render_markdown
from .scoring import AssessmentScorer
from .signals import SignalEngine


NY = ZoneInfo("America/New_York")


class RunStatus(StrEnum):
    SUCCESS = "success"
    SKIPPED_MARKET_CLOSED = "skipped_market_closed"
    DATA_FAILED = "data_failed"
    DELIVERY_FAILED = "delivery_failed"


@dataclass(frozen=True)
class RunResult:
    status: RunStatus
    candidate_count: int = 0
    failure_count: int = 0
    enrichment_failure_count: int = 0


@dataclass(frozen=True)
class Dependencies:
    calendar: object
    data: object
    signals: object
    sender_factory: Callable[[], object]
    output: Callable[[str], None] = print
    settings: Settings = field(default_factory=Settings)
    enrichment: object | None = None
    scorer: object | None = None


def _provider_summary(deps: Dependencies) -> str:
    market = deps.data.source_summary() if hasattr(deps.data, "source_summary") else "market=yahoo"
    news = "news=yahoo"
    if deps.enrichment is not None:
        provider = getattr(deps.enrichment, "providers", {}).get("event_news")
        if provider is not None and hasattr(provider, "source_summary"):
            news = provider.source_summary()
    return f"providers {market} {news} fundamentals=yahoo options=yahoo"


def run_scan(deps: Dependencies, *, now: datetime, send: bool) -> RunResult:
    session = deps.calendar.session_for(now.astimezone(NY).date())
    if session is None:
        return RunResult(RunStatus.SKIPPED_MARKET_CLOSED)

    signals = {}
    bars_by_symbol = {}
    failures: list[str] = []
    qqq_trend_ok = False
    benchmark_trends: dict[str, bool | None] = {"SPY": None, "QQQ": None}
    order = ("QQQ",) + tuple(symbol for symbol in SYMBOLS if symbol != "QQQ")
    for symbol in order:
        try:
            bars = deps.data.daily_history(symbol, session.opens_at)
            bars_by_symbol[symbol] = bars
            if symbol in benchmark_trends:
                benchmark_trends[symbol] = deps.signals.trend_qualifies(bars)
            if symbol == "QQQ":
                qqq_trend_ok = bool(benchmark_trends[symbol])
            signals[symbol] = deps.signals.evaluate(symbol, bars, qqq_trend_ok)
        except Exception:
            failures.append(symbol)
            signals[symbol] = None

    candidates = []
    quote_failures: list[str] = []
    for symbol in SYMBOLS:
        signal = signals.get(symbol)
        if signal is None:
            continue
        quote = deps.data.premarket_quote(symbol, now)
        if quote.status.value != "ok":
            quote_failures.append(symbol)
        candidates.append(evaluate_premarket(signal, quote, settings=deps.settings))
    candidates = rank_candidates(candidates)

    assessments = ()
    enrichment_failure_count = 0
    if candidates and deps.enrichment is not None and deps.scorer is not None:
        benchmarks = {symbol: bars_by_symbol[symbol] for symbol in ("SPY", "QQQ") if symbol in bars_by_symbol}
        contexts = tuple(
            CandidateInput(
                item.signal.symbol,
                item,
                bars_by_symbol[item.signal.symbol],
                benchmarks,
                item.quote.price if item.quote.status == QuoteStatus.OK else None,
                now,
            )
            for item in candidates
            if item.signal.symbol in bars_by_symbol
        )
        bundles = deps.enrichment.enrich(contexts)
        enrichment_failure_count = sum(
            any(
                result is not None and result.status == DimensionStatus.ERROR
                for result in (bundle.market, bundle.fundamental, bundle.event_news, bundle.options)
            )
            for bundle in bundles.values()
        )
        scored = []
        for item in contexts:
            try:
                scored.append(deps.scorer.score(item.candidate, bundles[item.symbol]))
            except Exception:
                enrichment_failure_count += 1
        assessments = tuple(scored)

    def benchmark_summary(symbol: str) -> str:
        trend = benchmark_trends[symbol]
        if trend is None:
            return f"{symbol} 数据异常"
        return f"{symbol} 趋势合格" if trend else f"{symbol} 趋势不合格"

    report = ScanReport(
        session=session,
        spy_summary=benchmark_summary("SPY"),
        qqq_summary=benchmark_summary("QQQ"),
        candidates=tuple(candidates),
        failures=tuple(dict.fromkeys((*failures, *quote_failures))),
        assessments=assessments,
    )
    if send:
        try:
            sender = deps.sender_factory()
            pages = render_png_pages(report) if assessments else (render_png(report),)
            for image_bytes in pages:
                sender.send_image(image_bytes)
        except Exception:
            return RunResult(RunStatus.DELIVERY_FAILED, len(candidates), len(failures), enrichment_failure_count)
    else:
        chunks = render_markdown(report)
        for chunk in chunks:
            deps.output(chunk)

    deps.output(_provider_summary(deps))

    status = RunStatus.DATA_FAILED if len(failures) == len(SYMBOLS) else RunStatus.SUCCESS
    return RunResult(status, len(candidates), len(failures), enrichment_failure_count)


def _dependencies(settings: Settings) -> Dependencies:
    yahoo_data = YahooMarketData(stale_minutes=settings.quote_stale_minutes)
    macro_calendar = MacroCalendar()
    yahoo_event_news = YahooEventNewsProvider(macro_calendar=macro_calendar, settings=settings)
    data = yahoo_data
    event_news = yahoo_event_news
    if settings.massive_api_key:
        massive_client = MassiveClient(
            settings.massive_api_key,
            base_url=settings.massive_base_url,
            timeout_seconds=settings.provider_timeout_seconds,
            retries=settings.provider_retries,
        )
        data = FallbackMarketData(
            MassiveMarketData(
                massive_client,
                stale_minutes=settings.quote_stale_minutes,
            ),
            yahoo_data,
        )
        event_news = FallbackEventNewsProvider(
            MassiveEventNewsProvider(
                massive_client,
                macro_calendar=macro_calendar,
                settings=settings,
            ),
            yahoo_event_news,
        )
    enrichment = EnrichmentRunner(
        YahooMarketContextProvider(),
        YahooFundamentalsProvider(),
        event_news,
        YahooOptionsProvider(settings=settings),
        settings,
    )
    return Dependencies(
        calendar=MarketSessionService(),
        data=data,
        signals=SignalEngine(settings),
        sender_factory=lambda: WeComClient(settings.wecom_webhook_url or ""),
        settings=settings,
        enrichment=enrichment,
        scorer=AssessmentScorer(settings),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan US equities before market open")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--send", action="store_true", help="send report to enterprise WeChat")
    mode.add_argument("--dry-run", action="store_true", help="print report only (default)")
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env(require_webhook=args.send)
    except ConfigError as exc:
        parser.error(str(exc))
    result = run_scan(_dependencies(settings), now=datetime.now(NY), send=args.send)
    if result.status in {RunStatus.SUCCESS, RunStatus.SKIPPED_MARKET_CLOSED}:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
