from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any


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
    higher_range: bool = False


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


class DimensionStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"
    ERROR = "error"


class RiskLevel(StrEnum):
    INFO = "info"
    CAUTION = "caution"
    HIGH = "high"


@dataclass(frozen=True)
class Evidence:
    key: str
    value: Any
    display: str
    source: str
    observed_at: datetime | None = None


@dataclass(frozen=True)
class RiskTag:
    level: RiskLevel
    code: str
    title: str
    detail: str


@dataclass(frozen=True)
class ProviderResult:
    dimension: str
    status: DimensionStatus
    evidence: tuple[Evidence, ...] = ()
    tags: tuple[RiskTag, ...] = ()


@dataclass(frozen=True)
class EnrichmentBundle:
    market: ProviderResult | None = None
    fundamental: ProviderResult | None = None
    event_news: ProviderResult | None = None
    options: ProviderResult | None = None


@dataclass(frozen=True)
class DimensionScore:
    name: str
    earned_points: int
    available_points: int
    status: DimensionStatus
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class CandidateAssessment:
    candidate: Candidate | None
    earned_points: int
    available_points: int
    completeness: float
    normalized_score: int | None
    dimensions: tuple[DimensionScore, ...]
    tags: tuple[RiskTag, ...] = ()
