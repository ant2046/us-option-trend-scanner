from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from market_scanner.data import MarketDataError
from market_scanner.massive_data import MassiveMarketData
from market_scanner.models import QuoteStatus


NY = ZoneInfo("America/New_York")


def epoch_ms(value: str) -> int:
    return int(pd.Timestamp(value, tz=NY).tz_convert("UTC").timestamp() * 1000)


def bar(value: str, close: float = 100.0):
    return {"o": close - 1, "h": close + 1, "l": close - 2, "c": close, "v": 1234, "t": epoch_ms(value)}


class Client:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def get(self, path, params=None, *, paginate=False):
        self.calls.append((path, params, paginate))
        return tuple(self.results)


def test_daily_history_maps_bars_to_previous_sessions():
    api = Client([bar("2026-11-17 00:00", 98), bar("2026-11-18 00:00", 99), bar("2026-11-19 00:00", 100)])
    data = MassiveMarketData(api)

    frame = data.daily_history("SPY", datetime(2026, 11, 20, 9, 30, tzinfo=NY))

    assert list(frame.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert frame["Close"].tolist() == [98.0, 99.0, 100.0]
    assert frame.index[-1].date().isoformat() == "2026-11-19"
    assert str(frame.index.tz) == "America/New_York"
    path, params, paginate = api.calls[0]
    assert path.startswith("/v2/aggs/ticker/SPY/range/1/day/")
    assert params["adjusted"] == "true"
    assert paginate is True


def test_daily_history_rejects_empty_malformed_and_stale_results():
    completed_before = datetime(2026, 11, 20, 9, 30, tzinfo=NY)

    with pytest.raises(MarketDataError, match="no usable daily data"):
        MassiveMarketData(Client([])).daily_history("SPY", completed_before)
    with pytest.raises(MarketDataError, match="malformed"):
        MassiveMarketData(Client([{"t": epoch_ms("2026-11-19 00:00"), "c": 100}])).daily_history("SPY", completed_before)
    with pytest.raises(MarketDataError, match="previous session"):
        MassiveMarketData(Client([bar("2026-11-18 00:00")])).daily_history("SPY", completed_before)


def test_premarket_uses_latest_valid_minute_and_excludes_future_or_regular_session():
    now = datetime(2026, 11, 20, 8, 30, tzinfo=NY)
    api = Client(
        [
            bar("2026-11-20 03:59", 90),
            bar("2026-11-20 08:10", 101),
            bar("2026-11-20 08:29", 102),
            bar("2026-11-20 08:31", 103),
            bar("2026-11-20 09:31", 104),
        ]
    )

    quote = MassiveMarketData(api, stale_minutes=15).premarket_quote("SPY", now)

    assert quote.status == QuoteStatus.OK
    assert quote.price == 102.0
    assert quote.observed_at == datetime(2026, 11, 20, 8, 29, tzinfo=NY)


def test_premarket_marks_exact_boundary_fresh_and_older_quote_stale():
    now = datetime(2026, 11, 20, 8, 30, tzinfo=NY)

    boundary = MassiveMarketData(Client([bar("2026-11-20 08:15", 101)]), stale_minutes=15).premarket_quote("SPY", now)
    stale = MassiveMarketData(Client([bar("2026-11-20 08:14", 101)]), stale_minutes=15).premarket_quote("SPY", now)

    assert boundary.status == QuoteStatus.OK
    assert stale.status == QuoteStatus.STALE


def test_premarket_returns_missing_for_empty_or_malformed_results():
    now = datetime(2026, 11, 20, 8, 30, tzinfo=NY)

    empty = MassiveMarketData(Client([])).premarket_quote("SPY", now)
    malformed = MassiveMarketData(Client([{"t": epoch_ms("2026-11-20 08:20")}])).premarket_quote("SPY", now)

    assert empty.status == QuoteStatus.MISSING
    assert malformed.status == QuoteStatus.ERROR
