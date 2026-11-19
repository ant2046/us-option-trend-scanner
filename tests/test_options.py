from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from market_scanner.config import Settings
from market_scanner.models import DimensionStatus
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
    assert values["spread_ratio"] == 0.2
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
