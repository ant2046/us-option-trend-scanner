"""Massive-only historical replay. No current-state enrichment or delivery."""
import argparse
import json
from dataclasses import replace
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import exchange_calendars as xcals
import pandas as pd

from .config import Settings
from .data import MarketDataError
from .main import NY, _dependencies, run_scan
from .massive import MassiveClient, MassiveError
from .massive_data import MassiveMarketData


class ReplayData:
    def __init__(self, client, first, last, calendar):
        self.client = client
        self.market = MassiveMarketData(client, calendar=calendar)
        self.calendar = calendar
        self.first = first
        self.last = last
        self.cache = {}

    def daily_history(self, symbol, cutoff):
        if symbol not in self.cache:
            rows = self.client.get(
                f"/v2/aggs/ticker/{symbol}/range/1/day/{self.first - timedelta(days=200)}/{self.last - timedelta(days=1)}",
                {"adjusted": "true", "sort": "asc", "limit": 50000}, paginate=True)
            self.cache[symbol] = self.market._frame(rows, NY)
        frame = self.cache[symbol]
        days = frame.index.date
        bars = frame.loc[(days >= cutoff.date() - timedelta(days=200)) & (days < cutoff.date())].dropna()
        if len(bars) < 60 or bars.index[-1].date() != self.calendar.previous_session(pd.Timestamp(cutoff.date())).date():
            raise MarketDataError("Incomplete historical daily bars")
        return bars

    def premarket_quote(self, symbol, now):
        quote = self.market.premarket_quote(symbol, now, completed_only=True)
        return replace(quote, source="massive" if quote.observed_at else None)

    def source_summary(self):
        return "market=massive_only"


def news_for(client, symbols, cutoff):
    end = cutoff.astimezone(timezone.utc)
    start = end - timedelta(hours=24)
    output = {}
    for symbol in sorted(symbols):
        try:
            rows = client.get("/v2/reference/news", {
                "ticker": symbol, "published_utc.gte": start.isoformat(),
                "published_utc.lte": end.isoformat(), "limit": 100,
            }, paginate=True)
            articles = []
            for row in rows:
                try:
                    stamp = datetime.fromisoformat(row["published_utc"].replace("Z", "+00:00"))
                    publisher = row["publisher"]["name"]
                    if start <= stamp <= end and row["title"] and publisher:
                        articles.append(dict(title=row["title"], published_utc=stamp.isoformat(), publisher=publisher))
                except (KeyError, AttributeError, TypeError, ValueError):
                    continue
            output[symbol] = dict(source="massive", status="ok" if articles else "no_usable_articles", articles=articles)
        except MassiveError as exc:
            output[symbol] = dict(source="massive", status="error", reason=str(exc))
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings.from_env(require_webhook=False)
    if not settings.massive_api_key:
        parser.error("Missing MASSIVE_API_KEY")
    calendar = xcals.get_calendar("XNYS")
    now = pd.Timestamp.now(tz="UTC")
    last = calendar.date_to_session(now.tz_convert(NY).date(), direction="previous")
    if calendar.session_close(last) > now:
        last = calendar.previous_session(last)
    sessions = calendar.sessions_window(last, -19)
    client = MassiveClient(settings.massive_api_key, retries=2)
    data = ReplayData(client, sessions[0].date(), last.date(), calendar)
    deps = replace(_dependencies(settings), data=data, enrichment=None, scorer=None, output=lambda _: None)
    summary = []
    for session in sessions:
        day = session.date()
        cutoff = datetime.combine(day, time(8, 30), NY)
        path = args.output / day.isoformat() / "scan.json"
        result = run_scan(deps, now=cutoff, send=False, archive=path, archive_metadata={
            "mode": "historical_replay", "source": "massive", "yahoo_fallback": False,
            "not_replayable": ["fundamentals", "earnings_calendar", "options_chain", "macro_calendar"],
            "combined_score": "not_replayable",
        })
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        snapshot.pop("providers", None)
        symbols = {"SPY", "QQQ"} | {c["signal"]["symbol"] for c in snapshot["report"]["candidates"]}
        news = news_for(client, symbols, cutoff)
        snapshot["news"] = news
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        summary.append(dict(date=day.isoformat(), status=result.status, candidates=result.candidate_count,
                            daily_failures=result.failure_count,
                            quotes_ok=sum(q["status"] == "ok" for q in snapshot["quotes"].values()),
                            quotes_requested=len(snapshot["quotes"]),
                            news_articles=sum(len(n.get("articles", [])) for n in news.values()),
                            news_errors=sum(n["status"] == "error" for n in news.values())))
        (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))
    return int(any(day["daily_failures"] or day["news_errors"] or
                   day["quotes_ok"] != day["quotes_requested"] for day in summary))


if __name__ == "__main__":
    raise SystemExit(main())
