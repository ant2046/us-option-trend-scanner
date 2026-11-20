from datetime import datetime, timezone

import pandas as pd
import pytest

from market_scanner.models import DimensionStatus
from market_scanner.providers import YahooFundamentalsProvider, YahooMarketContextProvider


def bars(values):
    count = len(values)
    return pd.DataFrame(
        {
            "Open": values,
            "High": [value + 1 for value in values],
            "Low": [value - 1 for value in values],
            "Close": values,
            "Volume": [1000] * count,
        },
        index=pd.date_range("2026-01-01", periods=count),
    )


def test_market_provider_reports_relative_returns_and_volatility():
    provider = YahooMarketContextProvider()
    result = provider.assess("AAPL", bars(list(range(80, 141))), {"SPY": bars(list(range(100, 161))), "QQQ": bars(list(range(90, 151)))})
    keys = {item.key for item in result.evidence}

    assert result.status == DimensionStatus.OK
    assert {"spy_trend", "qqq_trend", "relative_spy_20d", "relative_qqq_20d", "volatility_percentile"} <= keys


class FakeTicker:
    quarterly_financials = pd.DataFrame(
        {
            pd.Timestamp("2026-09-30"): [120.0, 24.0],
            pd.Timestamp("2025-09-30"): [100.0, 20.0],
        },
        index=["Total Revenue", "Net Income"],
    )
    quarterly_cashflow = pd.DataFrame(
        {pd.Timestamp("2026-09-30"): [18.0]}, index=["Free Cash Flow"]
    )
    info = {"profitMargins": 0.2, "debtToEquity": 80.0, "trailingPE": 25.0}


def test_fundamentals_provider_uses_quarterly_yoy_and_marks_benchmarks_not_applicable():
    provider = YahooFundamentalsProvider(ticker_factory=lambda symbol: FakeTicker(), now=lambda: datetime.now(timezone.utc))

    result = provider.assess("AAPL")
    values = {item.key: item.value for item in result.evidence}

    assert result.status == DimensionStatus.OK
    assert values["revenue_growth"] == pytest.approx(0.2)
    assert values["earnings_growth"] == pytest.approx(0.2)
    assert values["free_cash_flow"] == 18.0
    assert provider.assess("SPY").status == DimensionStatus.NOT_APPLICABLE


def test_market_provider_keeps_partial_evidence_when_one_benchmark_is_missing():
    result = YahooMarketContextProvider().assess("AAPL", bars(list(range(80, 141))), {"SPY": bars(list(range(100, 161)))})
    values = {item.key: item.value for item in result.evidence}
    assert result.status == DimensionStatus.PARTIAL
    assert values["spy_trend"] is True and values["qqq_trend"] is None
    assert values["relative_spy_20d"] is not None


def test_fundamentals_provider_matches_quarter_a_year_earlier_and_sanitizes_values():
    class RealShapeTicker:
        quarterly_financials = pd.DataFrame({
            pd.Timestamp("2026-09-30"): [120.0, 10.0], pd.Timestamp("2026-06-30"): [115.0, 9.0],
            pd.Timestamp("2026-03-31"): [110.0, 8.0], pd.Timestamp("2025-12-31"): [105.0, 7.0],
            pd.Timestamp("2025-09-30"): [100.0, -5.0],
        }, index=["Total Revenue", "Net Income"])
        quarterly_cashflow = FakeTicker.quarterly_cashflow
        info = {"profitMargins": 0.2, "debtToEquity": "unknown"}
    result = YahooFundamentalsProvider(ticker_factory=lambda symbol: RealShapeTicker()).assess("AAPL")
    values = {item.key: item.value for item in result.evidence}
    assert values["revenue_growth"] == pytest.approx(0.2)
    assert values["earnings_growth"] is None
    assert values["debt_to_equity"] is None


def test_fundamentals_provider_falls_back_to_annual_growth():
    class AnnualTicker:
        quarterly_financials = pd.DataFrame()
        quarterly_cashflow = pd.DataFrame()
        financials = pd.DataFrame({pd.Timestamp("2025-12-31"): [120.0, 24.0], pd.Timestamp("2024-12-31"): [100.0, 20.0]}, index=["Total Revenue", "Net Income"])
        cashflow = pd.DataFrame({pd.Timestamp("2025-12-31"): [18.0]}, index=["Free Cash Flow"])
        info = {}
    values = {item.key: item.value for item in YahooFundamentalsProvider(ticker_factory=lambda symbol: AnnualTicker()).assess("AAPL").evidence}
    assert values["revenue_growth"] == pytest.approx(0.2)
    assert values["earnings_growth"] == pytest.approx(0.2)
    assert values["free_cash_flow"] == 18.0
