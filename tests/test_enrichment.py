from datetime import datetime, timezone

import pandas as pd

from market_scanner.config import Settings
from market_scanner.enrichment import CandidateInput, EnrichmentRunner
from market_scanner.models import DimensionStatus, ProviderResult


class Provider:
    def __init__(self, dimension, *, error=False):
        self.dimension = dimension
        self.error = error

    def assess(self, *args):
        if self.error:
            raise RuntimeError("provider secret must not leak")
        return ProviderResult(self.dimension, DimensionStatus.OK)


def context(symbol="AAPL"):
    bars = pd.DataFrame(
        {"Close": [100.0, 102.0], "High": [101.0, 103.0], "Low": [99.0, 101.0], "Volume": [10, 11]},
        index=pd.date_range("2026-11-17", periods=2),
    )
    return CandidateInput(symbol, None, bars, {"SPY": bars, "QQQ": bars}, 103.0, datetime.now(timezone.utc))


def test_enrichment_runner_isolates_provider_failures():
    runner = EnrichmentRunner(
        Provider("market"), Provider("fundamental", error=True), Provider("event_news"), Provider("options"),
        Settings(enrichment_workers=4, enrichment_timeout_seconds=2),
    )

    result = runner.enrich((context(),))["AAPL"]

    assert result.market.status == DimensionStatus.OK
    assert result.fundamental.status == DimensionStatus.ERROR
    assert "secret" not in result.fundamental.evidence[0].display
    assert result.event_news.status == DimensionStatus.OK
    assert result.options.status == DimensionStatus.OK


def test_enrichment_runner_only_returns_requested_candidates():
    runner = EnrichmentRunner(Provider("market"), Provider("fundamental"), Provider("event_news"), Provider("options"), Settings())

    assert tuple(runner.enrich((context("NVDA"),))) == ("NVDA",)
