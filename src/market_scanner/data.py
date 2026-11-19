from __future__ import annotations

import time
from datetime import datetime
from typing import Callable

import pandas as pd
import yfinance as yf

from .models import PremarketQuote, QuoteStatus


REQUIRED_COLUMNS = ("Open", "High", "Low", "Close", "Volume")


class MarketDataError(RuntimeError):
    """Raised when market data is unavailable or malformed."""


class YahooMarketData:
    def __init__(
        self,
        *,
        ticker_factory: Callable[[str], object] = yf.Ticker,
        sleep: Callable[[float], None] = time.sleep,
        stale_minutes: int = 15,
    ):
        self._ticker_factory = ticker_factory
        self._sleep = sleep
        self._stale_minutes = stale_minutes

    def _history(self, symbol: str, **kwargs) -> pd.DataFrame:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return self._ticker_factory(symbol).history(timeout=10, **kwargs)
            except Exception as exc:  # provider exceptions are not stable types
                last_error = exc
                if attempt < 2:
                    self._sleep(2**attempt)
        raise MarketDataError(f"{symbol}: market data request failed") from last_error

    def daily_history(self, symbol: str, completed_before: datetime) -> pd.DataFrame:
        frame = self._history(
            symbol,
            period="6mo",
            interval="1d",
            auto_adjust=True,
            repair=True,
        )
        missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
        if missing:
            raise MarketDataError(f"{symbol}: missing columns {', '.join(missing)}")
        result = frame.loc[pd.DatetimeIndex(frame.index).date < completed_before.date(), list(REQUIRED_COLUMNS)]
        return result.dropna(how="all").copy()

    def premarket_quote(self, symbol: str, now: datetime) -> PremarketQuote:
        try:
            frame = self._history(
                symbol,
                period="1d",
                interval="1m",
                prepost=True,
                auto_adjust=True,
            )
        except MarketDataError as exc:
            return PremarketQuote(symbol, QuoteStatus.ERROR, None, None, str(exc))
        if frame.empty or "Close" not in frame.columns:
            return PremarketQuote(symbol, QuoteStatus.MISSING, None, None, "no premarket quote")
        closes = frame["Close"].dropna()
        if closes.empty:
            return PremarketQuote(symbol, QuoteStatus.MISSING, None, None, "no premarket quote")
        observed = pd.Timestamp(closes.index[-1]).to_pydatetime()
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=now.tzinfo)
        age_minutes = (now - observed.astimezone(now.tzinfo)).total_seconds() / 60
        status = QuoteStatus.STALE if age_minutes > self._stale_minutes else QuoteStatus.OK
        return PremarketQuote(symbol, status, float(closes.iloc[-1]), observed)
