from datetime import date, datetime, timezone

from market_scanner.config import Settings
from market_scanner.models import (
    Candidate,
    DimensionStatus,
    EnrichmentBundle,
    Evidence,
    PremarketQuote,
    ProviderResult,
    QuoteStatus,
    RiskLevel,
    RiskTag,
    TrendSignal,
)
from market_scanner.scoring import AssessmentScorer


NOW = datetime.now(timezone.utc)


def ev(key, value):
    return Evidence(key, value, str(value), "test", NOW)


def candidate(symbol="AAPL", *, status="允许关注", higher_range=False):
    signal = TrendSignal(symbol, date(2026, 11, 18), 100, 95, 90, 3, ("平台突破",), 92, higher_range)
    quote = PremarketQuote(symbol, QuoteStatus.OK, 101, NOW)
    return Candidate(signal, quote, 0.01, status)


def test_scorer_calculates_known_points_and_normalizes_only_above_completeness_threshold():
    market = ProviderResult("market", DimensionStatus.OK, (
        ev("spy_trend", True), ev("qqq_trend", True), ev("relative_spy_20d", 0.05),
        ev("relative_qqq_20d", 0.03), ev("volatility_percentile", 0.5),
    ))
    fundamental = ProviderResult("fundamental", DimensionStatus.PARTIAL, (ev("revenue_growth", 0.1),))
    event = ProviderResult("event_news", DimensionStatus.OK, (
        ev("earnings_days", 20), ev("macro_events", ()), ev("negative_headlines", ()), ev("news_fresh", True),
    ))
    options = ProviderResult("options", DimensionStatus.OK, (
        ev("expiry", "2026-12-18"), ev("spread_ratio", 0.05), ev("option_volume", 200),
        ev("open_interest", 800), ev("implied_volatility", 0.4),
    ))

    result = AssessmentScorer(Settings()).score(candidate(), EnrichmentBundle(market, fundamental, event, options))

    assert result.available_points == 85
    assert result.completeness == 0.85
    assert result.normalized_score == round(100 * result.earned_points / 85)
    assert [dimension.available_points for dimension in result.dimensions] == [30, 20, 5, 15, 15]


def test_missing_dimensions_are_not_zero_and_hide_normalized_score_below_seventy_percent():
    unavailable = ProviderResult("options", DimensionStatus.UNAVAILABLE)

    result = AssessmentScorer().score(candidate(), EnrichmentBundle(options=unavailable))

    assert result.available_points == 30
    assert result.completeness == 0.30
    assert result.normalized_score is None
    assert next(item for item in result.dimensions if item.name == "期权").available_points == 0


def test_not_applicable_fundamentals_do_not_lower_benchmark_completeness():
    bundle = EnrichmentBundle(fundamental=ProviderResult("fundamental", DimensionStatus.NOT_APPLICABLE))

    result = AssessmentScorer().score(candidate("SPY"), bundle)

    assert result.completeness == 30 / 80


def test_tags_are_deduplicated_and_sorted_high_before_caution_before_info():
    tags = (
        RiskTag(RiskLevel.INFO, "missing", "数据暂缺", "x"),
        RiskTag(RiskLevel.HIGH, "earnings", "3天内财报", "x"),
        RiskTag(RiskLevel.CAUTION, "spread", "价差偏大", "x"),
        RiskTag(RiskLevel.HIGH, "earnings", "重复", "x"),
    )
    bundle = EnrichmentBundle(event_news=ProviderResult("event_news", DimensionStatus.PARTIAL, tags=tags))

    result = AssessmentScorer().score(candidate(), bundle)

    assert [tag.code for tag in result.tags[:3]] == ["earnings", "spread", "missing"]
    assert {"market_data_missing", "fundamental_data_missing", "options_data_missing"} <= {tag.code for tag in result.tags}


def test_technical_higher_range_uses_explicit_signal_not_legacy_score():
    without = AssessmentScorer().score(candidate(higher_range=False), EnrichmentBundle())
    with_range = AssessmentScorer().score(candidate(higher_range=True), EnrichmentBundle())
    assert with_range.earned_points - without.earned_points == 4


def test_scorer_adds_candidate_and_missing_dimension_risk_tags():
    result = AssessmentScorer().score(candidate(status="信号失效"), EnrichmentBundle(market=ProviderResult("market", DimensionStatus.ERROR)))
    codes = {tag.code for tag in result.tags}
    assert "premarket_invalid" in codes and "market_data_missing" in codes
