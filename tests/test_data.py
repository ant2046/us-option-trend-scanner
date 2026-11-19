from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from market_scanner.data import MarketDataError, YahooMarketData
from market_scanner.models import QuoteStatus


NY = ZoneInfo("America/New_York")


class FakeTicker:
    def __init__(self, frames):
        self.frames = list(frames)
        self.calls = []

    def history(self, **kwargs):
        self.calls.append(kwargs)
        return self.frames.pop(0)


def bars(index, **overrides):
    values = {
        "Open": [10.0] * len(index),
        "High": [11.0] * len(index),
        "Low": [9.0] * len(index),
        "Close": [10.5] * len(index),
        "Volume": [1000] * len(index),
    }
    values.update(overrides)
    return pd.DataFrame(values, index=pd.DatetimeIndex(index))


def test_daily_history_drops_unfinished_session():
    frame = bars(pd.to_datetime(["2026-11-18", "2026-11-19"]))
    ticker = FakeTicker([frame])
    data = YahooMarketData(ticker_factory=lambda _: ticker, sleep=lambda _: None)

    result = data.daily_history("SPY", completed_before=datetime(2026, 11, 19, 8, 30, tzinfo=NY))

    assert list(result.index.date) == [datetime(2026, 11, 18).date()]
    assert ticker.calls[0].get("repair", False) is False


def test_daily_history_rejects_missing_ohlcv_column():
    frame = bars(pd.to_datetime(["2026-11-18"])).drop(columns="Volume")
    data = YahooMarketData(ticker_factory=lambda _: FakeTicker([frame]), sleep=lambda _: None)

    with pytest.raises(MarketDataError, match="Volume"):
        data.daily_history("SPY", completed_before=datetime(2026, 11, 19, 8, 30, tzinfo=NY))


def test_premarket_uses_latest_valid_minute():
    index = pd.DatetimeIndex([
        datetime(2026, 11, 19, 8, 20, tzinfo=NY),
        datetime(2026, 11, 19, 8, 29, tzinfo=NY),
    ])
    frame = bars(index, Close=[100.0, 101.0])
    data = YahooMarketData(ticker_factory=lambda _: FakeTicker([frame]), sleep=lambda _: None)

    quote = data.premarket_quote("SPY", datetime(2026, 11, 19, 8, 30, tzinfo=NY))

    assert quote.status == QuoteStatus.OK
    assert quote.price == 101.0
    assert quote.observed_at == index[-1].to_pydatetime()


def test_premarket_marks_stale_and_missing_quotes():
    stale_index = pd.DatetimeIndex([datetime(2026, 11, 19, 8, 0, tzinfo=NY)])
    stale_data = YahooMarketData(
        ticker_factory=lambda _: FakeTicker([bars(stale_index)]), sleep=lambda _: None
    )
    empty_data = YahooMarketData(
        ticker_factory=lambda _: FakeTicker([pd.DataFrame()]), sleep=lambda _: None
    )
    now = datetime(2026, 11, 19, 8, 30, tzinfo=NY)

    assert stale_data.premarket_quote("SPY", now).status == QuoteStatus.STALE
    assert empty_data.premarket_quote("SPY", now).status == QuoteStatus.MISSING
