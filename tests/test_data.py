from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from market_scanner.data import FallbackMarketData, MarketDataError, YahooMarketData
from market_scanner.models import PremarketQuote, QuoteStatus


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


def test_premarket_rejects_future_and_regular_session_bars():
    now = datetime(2026, 11, 19, 8, 30, tzinfo=NY)
    future = bars(pd.DatetimeIndex([datetime(2026, 11, 19, 8, 31, tzinfo=NY)]))
    regular = bars(pd.DatetimeIndex([datetime(2026, 11, 19, 9, 34, tzinfo=NY)]))
    future_data = YahooMarketData(ticker_factory=lambda _: FakeTicker([future]), sleep=lambda _: None)
    regular_data = YahooMarketData(ticker_factory=lambda _: FakeTicker([regular]), sleep=lambda _: None)

    assert future_data.premarket_quote("SPY", now).status == QuoteStatus.MISSING
    assert regular_data.premarket_quote("SPY", datetime(2026, 11, 19, 9, 35, tzinfo=NY)).status == QuoteStatus.MISSING


def test_daily_history_requires_immediately_previous_session():
    frame = bars(pd.to_datetime(["2026-11-17"]))
    data = YahooMarketData(ticker_factory=lambda _: FakeTicker([frame]), sleep=lambda _: None)

    with pytest.raises(MarketDataError, match="previous session"):
        data.daily_history("SPY", completed_before=datetime(2026, 11, 19, 8, 30, tzinfo=NY))


def test_empty_daily_response_is_provider_failure():
    empty = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    ticker = FakeTicker([empty, empty, empty])
    data = YahooMarketData(ticker_factory=lambda _: ticker, sleep=lambda _: None)

    with pytest.raises(MarketDataError, match="request failed"):
        data.daily_history("SPY", completed_before=datetime(2026, 11, 19, 8, 30, tzinfo=NY))
    assert len(ticker.calls) == 3


def test_daily_history_rejects_partial_previous_session_bar():
    frame = bars(
        pd.to_datetime(["2026-11-17", "2026-11-18"]),
        Volume=[1000, float("nan")],
    )
    data = YahooMarketData(ticker_factory=lambda _: FakeTicker([frame]), sleep=lambda _: None)

    with pytest.raises(MarketDataError, match="previous session"):
        data.daily_history("SPY", completed_before=datetime(2026, 11, 19, 8, 30, tzinfo=NY))


class Provider:
    def __init__(self, *, daily=None, quote=None, daily_error=None):
        self.daily = daily
        self.quote = quote
        self.daily_error = daily_error
        self.daily_calls = 0
        self.quote_calls = 0

    def daily_history(self, symbol, completed_before):
        self.daily_calls += 1
        if self.daily_error:
            raise self.daily_error
        return self.daily

    def premarket_quote(self, symbol, now):
        self.quote_calls += 1
        return self.quote


def valid_frame():
    return bars(pd.to_datetime(["2026-11-19"]))


def fallback_quote(status, price=None, minute=20):
    observed = datetime(2026, 11, 20, 8, minute, tzinfo=NY) if price is not None else None
    return PremarketQuote("SPY", status, price, observed, status.value)


def test_fallback_market_data_uses_primary_without_calling_backup():
    primary = Provider(daily=valid_frame(), quote=fallback_quote(QuoteStatus.OK, 101))
    backup = Provider(daily=valid_frame(), quote=fallback_quote(QuoteStatus.OK, 102))
    data = FallbackMarketData(primary, backup)

    assert data.daily_history("SPY", datetime(2026, 11, 20, 9, 30, tzinfo=NY)).iloc[-1]["Close"] == 10.5
    assert data.premarket_quote("SPY", datetime(2026, 11, 20, 8, 30, tzinfo=NY)).price == 101
    assert backup.daily_calls == 0
    assert backup.quote_calls == 0


@pytest.mark.parametrize("primary_daily", [pd.DataFrame(), None])
def test_fallback_market_data_uses_backup_for_invalid_daily_frame(primary_daily):
    primary = Provider(daily=primary_daily)
    backup = Provider(daily=valid_frame())

    result = FallbackMarketData(primary, backup).daily_history("SPY", datetime(2026, 11, 20, 9, 30, tzinfo=NY))

    assert result.iloc[-1]["Close"] == 10.5
    assert backup.daily_calls == 1


def test_fallback_market_data_uses_backup_after_daily_exception():
    primary = Provider(daily_error=MarketDataError("primary failed"))
    backup = Provider(daily=valid_frame())

    result = FallbackMarketData(primary, backup).daily_history("SPY", datetime(2026, 11, 20, 9, 30, tzinfo=NY))

    assert result.iloc[-1]["Close"] == 10.5


@pytest.mark.parametrize("status", [QuoteStatus.ERROR, QuoteStatus.MISSING, QuoteStatus.STALE])
def test_fallback_market_data_uses_ok_backup_for_non_ok_primary(status):
    primary = Provider(quote=fallback_quote(status, 99 if status == QuoteStatus.STALE else None, 10))
    backup = Provider(quote=fallback_quote(QuoteStatus.OK, 101, 25))

    result = FallbackMarketData(primary, backup).premarket_quote("SPY", datetime(2026, 11, 20, 8, 30, tzinfo=NY))

    assert result.status == QuoteStatus.OK
    assert result.price == 101


def test_fallback_market_data_retains_stale_primary_when_backup_has_less_information():
    primary = Provider(quote=fallback_quote(QuoteStatus.STALE, 99, 10))
    backup = Provider(quote=fallback_quote(QuoteStatus.ERROR))

    result = FallbackMarketData(primary, backup).premarket_quote("SPY", datetime(2026, 11, 20, 8, 30, tzinfo=NY))

    assert result.status == QuoteStatus.STALE
    assert result.price == 99


def test_fallback_market_data_reports_actual_fallback_usage():
    primary = Provider(daily=valid_frame(), quote=fallback_quote(QuoteStatus.STALE, 99, 10))
    backup = Provider(daily=valid_frame(), quote=fallback_quote(QuoteStatus.OK, 101, 25))
    data = FallbackMarketData(primary, backup)

    data.daily_history("SPY", datetime(2026, 11, 20, 9, 30, tzinfo=NY))
    data.premarket_quote("SPY", datetime(2026, 11, 20, 8, 30, tzinfo=NY))

    assert data.source_summary() == "market=massive+yahoo massive_successes=1 market_fallbacks=1"
