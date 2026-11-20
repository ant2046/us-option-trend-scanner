from __future__ import annotations

import pandas as pd

from .config import Settings
from .models import TrendSignal


class SignalEngine:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()

    def _prepare(self, bars: pd.DataFrame) -> pd.DataFrame:
        frame = bars.dropna(subset=["Open", "High", "Low", "Close", "Volume"]).copy()
        frame.index = pd.DatetimeIndex(frame.index).normalize()
        return frame.sort_index().loc[lambda item: ~item.index.duplicated(keep="last")]

    def trend_qualifies(self, bars: pd.DataFrame) -> bool:
        frame = self._prepare(bars)
        cfg = self.settings
        if len(frame) < 60:
            return False
        ma = frame["Close"].rolling(cfg.ma_short, min_periods=cfg.ma_short).mean()
        return bool(frame["Close"].iloc[-1] > ma.iloc[-1] and ma.iloc[-1] > ma.iloc[-1 - cfg.slope_lookback])

    def evaluate(
        self, symbol: str, bars: pd.DataFrame, qqq_trend_ok: bool | None
    ) -> TrendSignal | None:
        frame = self._prepare(bars)
        cfg = self.settings
        if not self.trend_qualifies(frame):
            return None

        frame["ma20"] = frame["Close"].rolling(cfg.ma_short, min_periods=cfg.ma_short).mean()
        frame["ma50"] = frame["Close"].rolling(cfg.ma_long, min_periods=cfg.ma_long).mean()
        latest = frame.iloc[-1]

        triggers: list[str] = []
        invalidations: list[float] = []

        recent = frame.iloc[-cfg.slope_lookback:]
        touched_ma20 = (
            (recent["Low"] >= recent["ma20"] * (1 - cfg.pullback_band))
            & (recent["Low"] <= recent["ma20"] * (1 + cfg.pullback_band))
        ).any()
        if touched_ma20 and latest["Close"] > frame["High"].iloc[-2]:
            triggers.append("回调转强")
            invalidations.append(float(min(recent["Low"].min(), latest["ma20"])))

        platform_high = float(frame["High"].shift(1).rolling(cfg.breakout_lookback, min_periods=cfg.breakout_lookback).max().iloc[-1])
        average_volume = float(
            frame["Volume"].shift(1).rolling(20, min_periods=20).mean().iloc[-1]
        )
        if latest["Close"] > platform_high and latest["Volume"] >= average_volume * cfg.breakout_volume_ratio:
            triggers.append("平台突破")
            invalidations.append(float(min(platform_high, latest["ma20"])))

        if not triggers:
            return None

        recent_ten = frame.iloc[-10:]
        prior_ten = frame.iloc[-20:-10]
        higher_range = (
            recent_ten["High"].max() > prior_ten["High"].max()
            and recent_ten["Low"].min() > prior_ten["Low"].min()
        )
        score = sum(
            (
                latest["Close"] > latest["ma50"],
                latest["ma20"] > latest["ma50"],
                higher_range,
                bool(qqq_trend_ok) if symbol not in {"SPY", "QQQ"} else False,
            )
        )
        return TrendSignal(
            symbol=symbol,
            session_date=frame.index[-1].date(),
            close=float(latest["Close"]),
            ma20=float(latest["ma20"]),
            ma50=float(latest["ma50"]),
            score=int(score),
            triggers=tuple(triggers),
            invalidation=min(invalidations),
            higher_range=bool(higher_range),
        )
