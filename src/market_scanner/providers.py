from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Mapping

import pandas as pd
import yfinance as yf

from .models import DimensionStatus, Evidence, ProviderResult


def _evidence(key, value, display, source="yahoo") -> Evidence:
    return Evidence(key, value, display, source, datetime.now(timezone.utc))


class YahooMarketContextProvider:
    @staticmethod
    def _trend(frame: pd.DataFrame) -> bool | None:
        closes = frame["Close"].dropna()
        if len(closes) < 25:
            return None
        ma20 = closes.rolling(20).mean()
        return bool(closes.iloc[-1] > ma20.iloc[-1] and ma20.iloc[-1] > ma20.iloc[-6])

    @staticmethod
    def _return(frame: pd.DataFrame) -> float | None:
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
    def _row(frame: pd.DataFrame, name: str) -> list[float]:
        if frame is None or frame.empty or name not in frame.index:
            return []
        values = frame.loc[name].dropna()
        values = values.reindex(sorted(values.index, reverse=True))
        return [float(value) for value in values.iloc[:2]]

    def assess(self, symbol: str) -> ProviderResult:
        if symbol in {"SPY", "QQQ"}:
            return ProviderResult("fundamental", DimensionStatus.NOT_APPLICABLE)
        ticker = self._ticker_factory(symbol)
        financials = getattr(ticker, "quarterly_financials", pd.DataFrame())
        cashflow = getattr(ticker, "quarterly_cashflow", pd.DataFrame())
        info = getattr(ticker, "info", {}) or {}
        revenue = self._row(financials, "Total Revenue")
        earnings = self._row(financials, "Net Income")
        fcf = self._row(cashflow, "Free Cash Flow")

        def growth(values):
            return values[0] / values[1] - 1 if len(values) >= 2 and values[1] else None

        observed = self._now()
        evidence = (
            Evidence("revenue_growth", growth(revenue), "营收同比", "yahoo-quarterly", observed),
            Evidence("earnings_growth", growth(earnings), "利润同比", "yahoo-quarterly", observed),
            Evidence("free_cash_flow", fcf[0] if fcf else None, "自由现金流", "yahoo-quarterly", observed),
            Evidence("profit_margin", info.get("profitMargins"), "净利率", "yahoo", observed),
            Evidence("debt_to_equity", info.get("debtToEquity"), "负债权益比", "yahoo", observed),
            Evidence("trailing_pe", info.get("trailingPE"), "市盈率", "yahoo", observed),
        )
        known = sum(item.value is not None for item in evidence[:5])
        status = DimensionStatus.OK if known == 5 else DimensionStatus.PARTIAL if known else DimensionStatus.UNAVAILABLE
        return ProviderResult("fundamental", status, evidence)
