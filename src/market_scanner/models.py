from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class QuoteStatus(StrEnum):
    OK = "ok"
    STALE = "stale"
    MISSING = "missing"
    ERROR = "error"


@dataclass(frozen=True)
class MarketSession:
    session_date: date
    opens_at: datetime


@dataclass(frozen=True)
class DailySnapshot:
    symbol: str
    session_date: date
    close: float
    ma20: float
    ma50: float


@dataclass(frozen=True)
class TrendSignal:
    symbol: str
    session_date: date
    close: float
    ma20: float
    ma50: float
    score: int
    triggers: tuple[str, ...]
    invalidation: float


@dataclass(frozen=True)
class PremarketQuote:
    symbol: str
    status: QuoteStatus
    price: float | None
    observed_at: datetime | None
    detail: str | None = None


@dataclass(frozen=True)
class Candidate:
    signal: TrendSignal
    quote: PremarketQuote
    premarket_change: float | None
    status: str
