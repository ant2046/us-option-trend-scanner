from __future__ import annotations

from .models import Candidate, PremarketQuote, QuoteStatus, TrendSignal


def evaluate_premarket(signal: TrendSignal, quote: PremarketQuote) -> Candidate:
    if quote.status != QuoteStatus.OK or quote.price is None:
        return Candidate(signal, quote, None, "数据异常")
    change = quote.price / signal.close - 1
    if quote.price < max(signal.ma20, signal.invalidation):
        status = "信号失效"
    elif quote.price > signal.close * 1.03:
        status = "跳空偏高，不追"
    else:
        status = "允许关注"
    return Candidate(signal, quote, change, status)


def rank_candidates(items: list[Candidate]) -> list[Candidate]:
    return sorted(
        items,
        key=lambda item: (
            -item.signal.score,
            abs(item.premarket_change) if item.premarket_change is not None else float("inf"),
            item.signal.symbol,
        ),
    )
