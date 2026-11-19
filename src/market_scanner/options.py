from __future__ import annotations

from datetime import date, datetime
from typing import Callable

import pandas as pd
import yfinance as yf

from .config import Settings
from .models import DimensionStatus, Evidence, ProviderResult, RiskLevel, RiskTag


class YahooOptionsProvider:
    def __init__(self, *, ticker_factory: Callable[[str], object] = yf.Ticker, settings: Settings | None = None):
        self.ticker_factory = ticker_factory
        self.settings = settings or Settings()

    @staticmethod
    def _nearest(frame: pd.DataFrame, spot: float) -> pd.Series | None:
        if frame is None or frame.empty or "strike" not in frame:
            return None
        return frame.loc[(frame["strike"] - spot).abs().idxmin()]

    def assess(self, symbol: str, spot: float | None, now: datetime) -> ProviderResult:
        if spot is None:
            return ProviderResult("options", DimensionStatus.UNAVAILABLE, tags=(RiskTag(RiskLevel.HIGH, "option_quote_missing", "期权无有效报价", "缺少现价"),))
        ticker = self.ticker_factory(symbol)
        expiries = []
        for raw in getattr(ticker, "options", ()) or ():
            expiry = date.fromisoformat(str(raw))
            days = (expiry - now.date()).days
            if self.settings.option_expiry_min_days <= days <= self.settings.option_expiry_max_days:
                expiries.append((days, str(raw)))
        if not expiries:
            return ProviderResult("options", DimensionStatus.UNAVAILABLE, tags=(RiskTag(RiskLevel.HIGH, "option_quote_missing", "期权无有效报价", "无合适到期日"),))
        expiry = min(expiries)[1]
        chain = ticker.option_chain(expiry)
        call = self._nearest(chain.calls, spot)
        put = self._nearest(chain.puts, spot)
        if call is None or put is None:
            return ProviderResult("options", DimensionStatus.UNAVAILABLE, tags=(RiskTag(RiskLevel.HIGH, "option_quote_missing", "期权无有效报价", "Call/Put 数据不完整"),))

        def number(row, key, default=0.0):
            value = row.get(key, default)
            return float(value) if pd.notna(value) else float(default)

        def spread(row):
            bid, ask = number(row, "bid"), number(row, "ask")
            return (ask - bid) / ask if ask > 0 and 0 <= bid <= ask else 1.0

        spread_ratio = max(spread(call), spread(put))
        volume = int(min(number(call, "volume"), number(put, "volume")))
        open_interest = int(min(number(call, "openInterest"), number(put, "openInterest")))
        ivs = [number(call, "impliedVolatility", float("nan")), number(put, "impliedVolatility", float("nan"))]
        valid_ivs = [value for value in ivs if pd.notna(value) and 0 < value <= 5]
        iv = sum(valid_ivs) / len(valid_ivs) if len(valid_ivs) == 2 else None
        evidence = (
            Evidence("expiry", expiry, expiry, "yahoo-options", now),
            Evidence("spread_ratio", spread_ratio, f"价差 {spread_ratio:.1%}", "yahoo-options", now),
            Evidence("option_volume", volume, f"成交量 {volume}", "yahoo-options", now),
            Evidence("open_interest", open_interest, f"未平仓 {open_interest}", "yahoo-options", now),
            Evidence("implied_volatility", iv, f"IV {iv:.1%}" if iv is not None else "IV异常", "yahoo-options", now),
        )
        tags: list[RiskTag] = []
        if spread_ratio > self.settings.option_max_spread_ratio:
            tags.append(RiskTag(RiskLevel.CAUTION, "option_spread_wide", "期权价差偏大", f"较差一侧 {spread_ratio:.1%}"))
        if volume < self.settings.option_min_volume or open_interest < self.settings.option_min_open_interest:
            tags.append(RiskTag(RiskLevel.CAUTION, "option_liquidity_low", "期权流动性偏低", f"量 {volume} / OI {open_interest}"))
        if iv is None:
            tags.append(RiskTag(RiskLevel.CAUTION, "option_iv_abnormal", "波动率数据异常", "Call/Put IV 不完整"))
        return ProviderResult("options", DimensionStatus.OK, evidence, tuple(tags))
