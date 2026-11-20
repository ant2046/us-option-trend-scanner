from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Callable, Mapping

import pandas as pd
import yfinance as yf

from .models import DimensionStatus, Evidence, ProviderResult


def _evidence(key, value, display, source="yahoo") -> Evidence:
    return Evidence(key, value, display, source, datetime.now(timezone.utc))


class YahooMarketContextProvider:
    @staticmethod
    def _trend(frame: pd.DataFrame) -> bool | None:
        if frame is None or "Close" not in frame:
            return None
        closes = frame["Close"].dropna()
        if len(closes) < 25:
            return None
        ma20 = closes.rolling(20).mean()
        return bool(closes.iloc[-1] > ma20.iloc[-1] and ma20.iloc[-1] > ma20.iloc[-6])

    @staticmethod
    def _return(frame: pd.DataFrame) -> float | None:
        if frame is None or "Close" not in frame:
            return None
        closes = frame["Close"].dropna()
        if len(closes) < 21:
            return None
        return float(closes.iloc[-1] / closes.iloc[-21] - 1)

    def assess(self, symbol: str, bars: pd.DataFrame, benchmarks: Mapping[str, pd.DataFrame]) -> ProviderResult:
        own_return = self._return(bars)
        spy_return = self._return(benchmarks.get("SPY", pd.DataFrame()))
        qqq_return = self._return(benchmarks.get("QQQ", pd.DataFrame()))
        returns = bars["Close"].pct_change().dropna()
        rolling = returns.rolling(20).std().dropna()
        percentile = None
        if not rolling.empty:
            percentile = float((rolling <= rolling.iloc[-1]).mean())
        evidence = (
            _evidence("spy_trend", self._trend(benchmarks.get("SPY", pd.DataFrame())), "SPY趋势"),
            _evidence("qqq_trend", self._trend(benchmarks.get("QQQ", pd.DataFrame())), "QQQ趋势"),
            _evidence("relative_spy_20d", None if own_return is None or spy_return is None else own_return - spy_return, "相对SPY"),
            _evidence("relative_qqq_20d", None if own_return is None or qqq_return is None else own_return - qqq_return, "相对QQQ"),
            _evidence("volatility_percentile", percentile, "波动率分位"),
        )
        status = DimensionStatus.OK if all(item.value is not None for item in evidence) else DimensionStatus.PARTIAL
        return ProviderResult("market", status, evidence)


class YahooFundamentalsProvider:
    def __init__(self, *, ticker_factory: Callable[[str], object] = yf.Ticker, now=lambda: datetime.now(timezone.utc)):
        self._ticker_factory = ticker_factory
        self._now = now

    @staticmethod
    def _series(frame: pd.DataFrame, name: str) -> pd.Series:
        if frame is None or frame.empty or name not in frame.index:
            return pd.Series(dtype=float)
        values = pd.to_numeric(frame.loc[name], errors="coerce").dropna()
        return values.reindex(sorted(values.index, reverse=True))

    @staticmethod
    def _finite(value):
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if isfinite(result) else None

    @classmethod
    def _yoy(cls, values: pd.Series):
        if values.empty:
            return None
        latest_date = pd.Timestamp(values.index[0])
        targets = [index for index in values.index[1:] if 350 <= (latest_date - pd.Timestamp(index)).days <= 380]
        if not targets:
            return None
        current, prior = cls._finite(values.iloc[0]), cls._finite(values.loc[targets[0]])
        if current is None or prior is None or prior <= 0:
            return None
        return current / prior - 1

    def assess(self, symbol: str) -> ProviderResult:
        if symbol in {"SPY", "QQQ"}:
            return ProviderResult("fundamental", DimensionStatus.NOT_APPLICABLE)
        ticker = self._ticker_factory(symbol)
        financials = getattr(ticker, "quarterly_financials", pd.DataFrame())
        cashflow = getattr(ticker, "quarterly_cashflow", pd.DataFrame())
        annual_financials = getattr(ticker, "financials", pd.DataFrame())
        annual_cashflow = getattr(ticker, "cashflow", pd.DataFrame())
        info = getattr(ticker, "info", {}) or {}
        revenue = self._series(financials, "Total Revenue")
        earnings = self._series(financials, "Net Income")
        fcf = self._series(cashflow, "Free Cash Flow")
        annual_revenue = self._series(annual_financials, "Total Revenue")
        annual_earnings = self._series(annual_financials, "Net Income")
        annual_fcf = self._series(annual_cashflow, "Free Cash Flow")
        revenue_growth = self._yoy(revenue)
        earnings_growth = self._yoy(earnings)
        if revenue_growth is None:
            revenue_growth = self._yoy(annual_revenue)
        if earnings_growth is None:
            earnings_growth = self._yoy(annual_earnings)
        if fcf.empty:
            fcf = annual_fcf

        observed = self._now()
        evidence = (
            Evidence("revenue_growth", revenue_growth, "营收同比", "yahoo", observed),
            Evidence("earnings_growth", earnings_growth, "利润同比", "yahoo", observed),
            Evidence("free_cash_flow", self._finite(fcf.iloc[0]) if not fcf.empty else None, "自由现金流", "yahoo-quarterly", observed),
            Evidence("profit_margin", self._finite(info.get("profitMargins")), "净利率", "yahoo", observed),
            Evidence("debt_to_equity", self._finite(info.get("debtToEquity")), "负债权益比", "yahoo", observed),
            Evidence("trailing_pe", self._finite(info.get("trailingPE")), "市盈率", "yahoo", observed),
        )
        known = sum(item.value is not None for item in evidence[:5])
        status = DimensionStatus.OK if known == 5 else DimensionStatus.PARTIAL if known else DimensionStatus.UNAVAILABLE
        return ProviderResult("fundamental", status, evidence)
