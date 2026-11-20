from datetime import datetime, timezone
from time import monotonic, sleep

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


def test_enrichment_deadline_returns_without_waiting_for_blocked_provider():
    class SlowProvider(Provider):
        def assess(self, *args):
            sleep(0.25)
            return super().assess(*args)

    runner = EnrichmentRunner(SlowProvider("market"), SlowProvider("fundamental"), SlowProvider("event_news"), SlowProvider("options"), Settings(enrichment_workers=4, enrichment_timeout_seconds=0.02, provider_timeout_seconds=0.01))
    started = monotonic()
    result = runner.enrich((context(),))["AAPL"]
    assert monotonic() - started < 0.12
    assert result.market.status == DimensionStatus.ERROR


def test_enrichment_retries_one_transient_provider_error():
    class FlakyProvider(Provider):
        def __init__(self, dimension):
            super().__init__(dimension)
            self.calls = 0
        def assess(self, *args):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("temporary")
            return super().assess(*args)
    flaky = FlakyProvider("market")
    runner = EnrichmentRunner(flaky, Provider("fundamental"), Provider("event_news"), Provider("options"), Settings(provider_retries=1))
    assert runner.enrich((context(),))["AAPL"].market.status == DimensionStatus.OK
    assert flaky.calls == 2
