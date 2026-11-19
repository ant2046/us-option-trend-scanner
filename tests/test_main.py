from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from market_scanner.main import Dependencies, RunStatus, run_scan
from market_scanner.models import MarketSession, PremarketQuote, QuoteStatus, TrendSignal


NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 19, 8, 30, tzinfo=NY)


class FakeCalendar:
    def __init__(self, opened=True):
        self.opened = opened

    def session_for(self, value):
        return MarketSession(value, value_to_open(value)) if self.opened else None


def value_to_open(value):
    return datetime(value.year, value.month, value.day, 9, 30, tzinfo=NY)


class FakeData:
    def __init__(self, failing=()):
        self.failing = set(failing)
        self.daily_calls = []

    def daily_history(self, symbol, completed_before):
        self.daily_calls.append(symbol)
        if symbol in self.failing:
            raise RuntimeError("failed")
        return pd.DataFrame({"symbol": [symbol]})

    def premarket_quote(self, symbol, now):
        return PremarketQuote(symbol, QuoteStatus.OK, 101, now)


class FakeSignals:
    def evaluate(self, symbol, bars, qqq_trend_ok):
        return TrendSignal(symbol, date(2026, 11, 18), 100, 95, 90, 4, ("平台突破",), 92)


class Sender:
    def __init__(self, fail=False):
        self.messages = []
        self.fail = fail

    def send(self, message):
        if self.fail:
            raise RuntimeError("send failed")
        self.messages.append(message)


def deps(data=None, opened=True, sender=None, output=None):
    sender = sender or Sender()
    return Dependencies(FakeCalendar(opened), data or FakeData(), FakeSignals(), lambda: sender, output or (lambda _: None))


def test_closed_market_skips_data_and_send():
    data = FakeData()
    sender = Sender()
    result = run_scan(deps(data, opened=False, sender=sender), now=NOW, send=True)
    assert result.status == RunStatus.SKIPPED_MARKET_CLOSED
    assert data.daily_calls == []
    assert sender.messages == []


def test_normal_flow_fetches_qqq_first_and_sends_once():
    data = FakeData()
    sender = Sender()
    result = run_scan(deps(data, sender=sender), now=NOW, send=True)
    assert result.status == RunStatus.SUCCESS
    assert data.daily_calls[0] == "QQQ"
    assert len(sender.messages) == 1
    assert "AAPL" in sender.messages[0]


def test_one_symbol_failure_is_listed_but_scan_succeeds():
    sender = Sender()
    result = run_scan(deps(FakeData(failing=("TSLA",)), sender=sender), now=NOW, send=True)
    assert result.status == RunStatus.SUCCESS
    assert "TSLA" in sender.messages[0]


def test_all_daily_failures_return_data_failed():
    data = FakeData(failing=("SPY", "QQQ", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"))
    result = run_scan(deps(data), now=NOW, send=False)
    assert result.status == RunStatus.DATA_FAILED


def test_dry_run_prints_without_constructing_sender():
    output = []
    dependencies = Dependencies(FakeCalendar(), FakeData(), FakeSignals(), lambda: (_ for _ in ()).throw(AssertionError("sender constructed")), output.append)
    result = run_scan(dependencies, now=NOW, send=False)
    assert result.status == RunStatus.SUCCESS
    assert output and "美股盘前趋势扫描" in output[0]


def test_send_failure_returns_delivery_failed():
    result = run_scan(deps(sender=Sender(fail=True)), now=NOW, send=True)
    assert result.status == RunStatus.DELIVERY_FAILED
