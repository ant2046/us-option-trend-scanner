from __future__ import annotations

from .config import Settings
from .models import (
    Candidate,
    CandidateAssessment,
    DimensionScore,
    DimensionStatus,
    EnrichmentBundle,
    Evidence,
    ProviderResult,
    RiskLevel,
    RiskTag,
)


class AssessmentScorer:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()

    @staticmethod
    def _values(result: ProviderResult | None) -> dict[str, object]:
        return {item.key: item.value for item in result.evidence} if result else {}

    @staticmethod
    def _dimension(name: str, result: ProviderResult | None, weights: dict[str, tuple[int, callable]], *, freshness: int = 0) -> DimensionScore:
        if result is None:
            return DimensionScore(name, 0, 0, DimensionStatus.UNAVAILABLE)
        if result.status in {DimensionStatus.UNAVAILABLE, DimensionStatus.ERROR, DimensionStatus.NOT_APPLICABLE}:
            return DimensionScore(name, 0, 0, result.status, result.evidence)
        values = {item.key: item.value for item in result.evidence}
        earned = 0
        available = 0
        for key, (points, predicate) in weights.items():
            value = values.get(key)
            if value is None:
                continue
            available += points
            if predicate(value):
                earned += points
        if freshness:
            available += freshness
            earned += freshness
        return DimensionScore(name, earned, available, result.status, result.evidence)

    @staticmethod
    def _technical(candidate: Candidate) -> DimensionScore:
        signal = candidate.signal
        earned = 8
        earned += 4 if signal.close > signal.ma50 else 0
        earned += 4 if signal.ma20 > signal.ma50 else 0
        earned += 4 if signal.score >= 3 else 0
        earned += 5 if "回调转强" in signal.triggers else 0
        earned += 5 if "平台突破" in signal.triggers else 0
        return DimensionScore("技术", min(30, earned), 30, DimensionStatus.OK)

    @staticmethod
    def _ordered_tags(bundle: EnrichmentBundle) -> tuple[RiskTag, ...]:
        raw = []
        for result in (bundle.market, bundle.fundamental, bundle.event_news, bundle.options):
            if result:
                raw.extend(result.tags)
        severity = {RiskLevel.HIGH: 0, RiskLevel.CAUTION: 1, RiskLevel.INFO: 2}
        seen: set[str] = set()
        unique = []
        for tag in sorted(raw, key=lambda item: severity[item.level]):
            if tag.code not in seen:
                seen.add(tag.code)
                unique.append(tag)
        return tuple(unique)

    def score(self, candidate: Candidate, bundle: EnrichmentBundle) -> CandidateAssessment:
        dimensions = (
            self._technical(candidate),
            self._dimension("环境", bundle.market, {
                "spy_trend": (5, bool), "qqq_trend": (5, bool),
                "relative_spy_20d": (4, lambda value: value > 0),
                "relative_qqq_20d": (3, lambda value: value > 0),
                "volatility_percentile": (3, lambda value: value <= 0.8),
            }),
            self._dimension("基本面", bundle.fundamental, {
                "revenue_growth": (5, lambda value: value > 0),
                "earnings_growth": (5, lambda value: value > 0),
                "free_cash_flow": (4, lambda value: value > 0),
                "profit_margin": (3, lambda value: value > 0),
                "debt_to_equity": (3, lambda value: value <= 200),
            }),
            self._dimension("事件消息", bundle.event_news, {
                "earnings_days": (6, lambda value: value > 7),
                "macro_events": (4, lambda value: len(value) == 0),
                "negative_headlines": (3, lambda value: len(value) == 0),
            }, freshness=2 if bundle.event_news and bundle.event_news.status in {DimensionStatus.OK, DimensionStatus.PARTIAL} else 0),
            self._dimension("期权", bundle.options, {
                "expiry": (3, lambda value: bool(value)),
                "spread_ratio": (4, lambda value: value <= self.settings.option_max_spread_ratio),
                "open_interest": (3, lambda value: value >= self.settings.option_min_open_interest),
                "option_volume": (2, lambda value: value >= self.settings.option_min_volume),
                "implied_volatility": (3, lambda value: 0 < value <= 5),
            }),
        )
        earned = sum(item.earned_points for item in dimensions)
        available = sum(item.available_points for item in dimensions)
        applicable_max = 80 if candidate.signal.symbol in {"SPY", "QQQ"} else 100
        completeness = available / applicable_max
        normalized = round(100 * earned / available) if available and completeness >= self.settings.normalized_score_min_completeness else None
        return CandidateAssessment(candidate, earned, available, completeness, normalized, dimensions, self._ordered_tags(bundle))
