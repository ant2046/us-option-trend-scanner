from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from market_scanner.models import PremarketQuote, QuoteStatus, TrendSignal
from market_scanner.premarket import evaluate_premarket, rank_candidates


NY = ZoneInfo("America/New_York")


def signal(symbol="AAPL", score=3):
    return TrendSignal(symbol, date(2026, 11, 18), 100, 95, 90, score, ("平台突破",), 92)


def quote(symbol="AAPL", price=101, status=QuoteStatus.OK):
    observed = datetime(2026, 11, 19, 8, 30, tzinfo=NY) if price is not None else None
    return PremarketQuote(symbol, status, price, observed)


@pytest.mark.parametrize(
    ("price", "expected"),
    [(103.01, "跳空偏高，不追"), (103.0, "允许关注"), (91.0, "信号失效")],
)
def test_premarket_status_boundaries(price, expected):
    assert evaluate_premarket(signal(), quote(price=price)).status == expected


@pytest.mark.parametrize("status", [QuoteStatus.STALE, QuoteStatus.MISSING, QuoteStatus.ERROR])
def test_bad_quote_is_data_error_without_change(status):
    item = evaluate_premarket(signal(), quote(price=None, status=status))
    assert item.status == "数据异常"
    assert item.premarket_change is None


def test_rank_by_score_then_smaller_absolute_gap_then_symbol():
    items = [
        evaluate_premarket(signal("TSLA", 4), quote("TSLA", 102)),
        evaluate_premarket(signal("NVDA", 4), quote("NVDA", 101)),
        evaluate_premarket(signal("AAPL", 3), quote("AAPL", 100)),
    ]
    assert [item.signal.symbol for item in rank_candidates(items)] == ["NVDA", "TSLA", "AAPL"]


def test_gap_limit_comes_from_settings():
    from market_scanner.config import Settings

    item = evaluate_premarket(signal(), quote(price=102.5), settings=Settings(gap_limit=0.02))
    assert item.status == "跳空偏高，不追"
