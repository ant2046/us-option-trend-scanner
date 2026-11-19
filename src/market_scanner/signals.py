from __future__ import annotations

import pandas as pd

from .models import TrendSignal


class SignalEngine:
    def evaluate(
        self, symbol: str, bars: pd.DataFrame, qqq_trend_ok: bool | None
    ) -> TrendSignal | None:
        frame = bars.dropna(subset=["Open", "High", "Low", "Close", "Volume"]).copy()
        if len(frame) < 60:
            return None

        frame["ma20"] = frame["Close"].rolling(20, min_periods=20).mean()
        frame["ma50"] = frame["Close"].rolling(50, min_periods=50).mean()
        latest = frame.iloc[-1]
        if latest["Close"] <= latest["ma20"] or latest["ma20"] <= frame["ma20"].iloc[-6]:
            return None

        triggers: list[str] = []
        invalidations: list[float] = []

        recent = frame.iloc[-5:]
        touched_ma20 = (
            (recent["Low"] >= recent["ma20"] * 0.98)
            & (recent["Low"] <= recent["ma20"] * 1.02)
        ).any()
        if touched_ma20 and latest["Close"] > frame["High"].iloc[-2]:
            triggers.append("回调转强")
            invalidations.append(float(min(recent["Low"].min(), latest["ma20"])))

        platform_high = float(frame["High"].shift(1).rolling(10, min_periods=10).max().iloc[-1])
        average_volume = float(
            frame["Volume"].shift(1).rolling(20, min_periods=20).mean().iloc[-1]
        )
        if latest["Close"] > platform_high and latest["Volume"] >= average_volume * 1.2:
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
        )
