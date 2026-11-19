from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Callable
from zoneinfo import ZoneInfo

from .calendar import MarketSessionService
from .config import ConfigError, Settings, SYMBOLS
from .data import YahooMarketData
from .premarket import evaluate_premarket, rank_candidates
from .report import ScanReport, WeComClient, render_markdown
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


@dataclass(frozen=True)
class Dependencies:
    calendar: object
    data: object
    signals: object
    sender_factory: Callable[[], object]
    output: Callable[[str], None] = print
    settings: Settings = field(default_factory=Settings)


def run_scan(deps: Dependencies, *, now: datetime, send: bool) -> RunResult:
    session = deps.calendar.session_for(now.astimezone(NY).date())
    if session is None:
        return RunResult(RunStatus.SKIPPED_MARKET_CLOSED)

    signals = {}
    failures: list[str] = []
    qqq_trend_ok = False
    order = ("QQQ",) + tuple(symbol for symbol in SYMBOLS if symbol != "QQQ")
    for symbol in order:
        try:
            bars = deps.data.daily_history(symbol, session.opens_at)
            if symbol == "QQQ":
                qqq_trend_ok = deps.signals.trend_qualifies(bars)
            signals[symbol] = deps.signals.evaluate(symbol, bars, qqq_trend_ok)
        except Exception:
            failures.append(symbol)
            signals[symbol] = None

    candidates = []
    for symbol in SYMBOLS:
        signal = signals.get(symbol)
        if signal is None:
            continue
        quote = deps.data.premarket_quote(symbol, now)
        candidates.append(evaluate_premarket(signal, quote, settings=deps.settings))
    candidates = rank_candidates(candidates)

    report = ScanReport(
        session=session,
        spy_summary="SPY 合格" if signals.get("SPY") else "SPY 无触发",
        qqq_summary="QQQ 合格" if signals.get("QQQ") else "QQQ 无触发",
        candidates=tuple(candidates),
        failures=tuple(failures),
    )
    chunks = render_markdown(report)
    if send:
        try:
            sender = deps.sender_factory()
            for chunk in chunks:
                sender.send(chunk)
        except Exception:
            return RunResult(RunStatus.DELIVERY_FAILED, len(candidates), len(failures))
    else:
        for chunk in chunks:
            deps.output(chunk)

    status = RunStatus.DATA_FAILED if len(failures) == len(SYMBOLS) else RunStatus.SUCCESS
    return RunResult(status, len(candidates), len(failures))


def _dependencies(settings: Settings) -> Dependencies:
    return Dependencies(
        calendar=MarketSessionService(),
        data=YahooMarketData(stale_minutes=settings.quote_stale_minutes),
        signals=SignalEngine(settings),
        sender_factory=lambda: WeComClient(settings.wecom_webhook_url or ""),
        settings=settings,
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
