from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from market_scanner.models import (
    CandidateAssessment,
    DimensionScore,
    DimensionStatus,
    EnrichmentBundle,
    Evidence,
    ProviderResult,
    RiskLevel,
    RiskTag,
)


def test_assessment_models_are_immutable_and_preserve_unknown_dimensions():
    evidence = Evidence("revenue_growth", 0.12, "+12%", "yahoo", datetime.now(timezone.utc))
    tag = RiskTag(RiskLevel.CAUTION, "earnings_soon", "3天内财报", "预计盘后")
    result = ProviderResult("fundamental", DimensionStatus.PARTIAL, (evidence,), (tag,))
    bundle = EnrichmentBundle(fundamental=result)
    score = DimensionScore("基本面", 5, 10, DimensionStatus.PARTIAL, (evidence,))
    assessment = CandidateAssessment(None, 5, 10, 0.5, None, (score,), (tag,))

    assert bundle.fundamental == result
    assert assessment.normalized_score is None
    with pytest.raises(FrozenInstanceError):
        assessment.earned_points = 6


def test_dimension_and_risk_enums_have_stable_wire_values():
    assert [item.value for item in DimensionStatus] == [
        "ok", "partial", "unavailable", "not_applicable", "error"
    ]
    assert [item.value for item in RiskLevel] == ["info", "caution", "high"]
