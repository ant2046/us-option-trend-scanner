from __future__ import annotations

from datetime import date, datetime
from math import isfinite
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

        def number(row, key):
            value = row.get(key)
            if value is None or pd.isna(value):
                return None
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                return None
            return parsed if isfinite(parsed) else None

        def spread(row):
            bid, ask = number(row, "bid"), number(row, "ask")
            if bid is None or ask is None or bid <= 0 or ask <= 0 or bid > ask:
                return None
            return (ask - bid) / ((ask + bid) / 2)

        spreads = [spread(call), spread(put)]
        if any(value is None for value in spreads):
            return ProviderResult("options", DimensionStatus.UNAVAILABLE, tags=(RiskTag(RiskLevel.HIGH, "option_quote_missing", "期权无有效报价", "Call/Put 买卖报价缺失或交叉"),))
        spread_ratio = max(spreads)
        raw_volumes = [number(call, "volume"), number(put, "volume")]
        raw_oi = [number(call, "openInterest"), number(put, "openInterest")]
        volume = int(min(raw_volumes)) if all(value is not None for value in raw_volumes) else None
        open_interest = int(min(raw_oi)) if all(value is not None for value in raw_oi) else None
        ivs = [number(call, "impliedVolatility"), number(put, "impliedVolatility")]
        iv = sum(ivs) / 2 if all(value is not None and 0 < value <= 5 for value in ivs) else None
        evidence = (
            Evidence("expiry", expiry, expiry, "yahoo-options", now),
            Evidence("spread_ratio", spread_ratio, f"价差 {spread_ratio:.1%}", "yahoo-options", now),
            Evidence("option_volume", volume, f"成交量 {volume}" if volume is not None else "成交量暂缺", "yahoo-options", now),
            Evidence("open_interest", open_interest, f"未平仓 {open_interest}" if open_interest is not None else "未平仓暂缺", "yahoo-options", now),
            Evidence("implied_volatility", iv, f"IV {iv:.1%}" if iv is not None else "IV暂缺", "yahoo-options", now),
        )
        tags: list[RiskTag] = []
        if spread_ratio > 0.15:
            tags.append(RiskTag(RiskLevel.CAUTION, "option_spread_wide", "期权价差偏大", f"较差一侧 {spread_ratio:.1%}"))
        if (volume is not None and volume < self.settings.option_min_volume) or (open_interest is not None and open_interest < self.settings.option_min_open_interest):
            tags.append(RiskTag(RiskLevel.CAUTION, "option_liquidity_low", "期权流动性偏低", f"量 {volume} / OI {open_interest}"))
        status = DimensionStatus.OK if volume is not None and open_interest is not None and iv is not None else DimensionStatus.PARTIAL
        return ProviderResult("options", status, evidence, tuple(tags))
