from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from market_scanner.config import Settings
from market_scanner.models import DimensionStatus, RiskLevel
from market_scanner.options import YahooOptionsProvider


NY = ZoneInfo("America/New_York")


class Chain:
    calls = pd.DataFrame([
        {"strike": 100.0, "bid": 4.5, "ask": 5.0, "volume": 200, "openInterest": 800, "impliedVolatility": 0.4}
    ])
    puts = pd.DataFrame([
        {"strike": 100.0, "bid": 4.0, "ask": 5.0, "volume": 50, "openInterest": 400, "impliedVolatility": 0.5}
    ])


class FakeTicker:
    options = ("2026-11-27", "2026-12-18", "2027-01-15")

    def option_chain(self, expiry):
        assert expiry == "2026-12-18"
        return Chain()


def test_options_provider_uses_worse_call_put_liquidity_and_nearest_eligible_expiry():
    provider = YahooOptionsProvider(ticker_factory=lambda symbol: FakeTicker(), settings=Settings())

    result = provider.assess("AAPL", 101.0, datetime(2026, 11, 19, 8, 30, tzinfo=NY))
    values = {item.key: item.value for item in result.evidence}

    assert result.status == DimensionStatus.OK
    assert values["expiry"] == "2026-12-18"
    assert values["spread_ratio"] == pytest.approx(2 / 9)
    assert values["option_volume"] == 50
    assert values["open_interest"] == 400
    assert values["implied_volatility"] == 0.45
    assert {tag.code for tag in result.tags} == {"option_spread_wide", "option_liquidity_low"}


def test_options_provider_marks_missing_quote_unavailable():
    class EmptyTicker(FakeTicker):
        def option_chain(self, expiry):
            chain = Chain()
            chain.puts = pd.DataFrame()
            return chain

    result = YahooOptionsProvider(ticker_factory=lambda symbol: EmptyTicker()).assess(
        "AAPL", 101.0, datetime(2026, 11, 19, 8, 30, tzinfo=NY)
    )

    assert result.status == DimensionStatus.UNAVAILABLE
    assert any(tag.code == "option_quote_missing" for tag in result.tags)


def test_options_provider_uses_midpoint_spread_and_preserves_unknown_liquidity():
    class PartialChain:
        calls = pd.DataFrame([{"strike": 100.0, "bid": 9.0, "ask": 10.0, "volume": None, "openInterest": None, "impliedVolatility": None}])
        puts = pd.DataFrame([{"strike": 100.0, "bid": 9.0, "ask": 10.0, "volume": 200, "openInterest": 800, "impliedVolatility": 0.4}])
    class PartialTicker(FakeTicker):
        def option_chain(self, expiry): return PartialChain()
    result = YahooOptionsProvider(ticker_factory=lambda symbol: PartialTicker()).assess("AAPL", 100.0, datetime(2026, 11, 19, 8, 30, tzinfo=NY))
    values = {item.key: item.value for item in result.evidence}
    assert values["spread_ratio"] == pytest.approx(1 / 9.5)
    assert values["option_volume"] is None and values["open_interest"] is None
    assert values["implied_volatility"] is None
    assert result.status == DimensionStatus.PARTIAL
    assert "option_liquidity_low" not in {tag.code for tag in result.tags}


def test_options_provider_marks_crossed_quote_high_risk():
    class BadChain:
        calls = pd.DataFrame([{"strike": 100.0, "bid": 10.0, "ask": 9.0}])
        puts = pd.DataFrame([{"strike": 100.0, "bid": 4.0, "ask": 5.0}])
    class BadTicker(FakeTicker):
        def option_chain(self, expiry): return BadChain()
    result = YahooOptionsProvider(ticker_factory=lambda symbol: BadTicker()).assess("AAPL", 100.0, datetime(2026, 11, 19, 8, 30, tzinfo=NY))
    assert result.status == DimensionStatus.UNAVAILABLE
    assert next(tag for tag in result.tags if tag.code == "option_quote_missing").level == RiskLevel.HIGH
