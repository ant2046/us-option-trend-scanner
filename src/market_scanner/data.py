from __future__ import annotations

import time
from datetime import datetime
from typing import Callable

import pandas as pd
import yfinance as yf
import exchange_calendars as xcals

from .models import PremarketQuote, QuoteStatus


REQUIRED_COLUMNS = ("Open", "High", "Low", "Close", "Volume")


class MarketDataError(RuntimeError):
    """Raised when market data is unavailable or malformed."""


class FallbackMarketData:
    def __init__(self, primary, fallback):
        self._primary = primary
        self._fallback = fallback

    @staticmethod
    def _valid_daily(frame) -> bool:
        return (
            isinstance(frame, pd.DataFrame)
            and not frame.empty
            and all(column in frame.columns for column in REQUIRED_COLUMNS)
        )

    def daily_history(self, symbol: str, completed_before: datetime) -> pd.DataFrame:
        try:
            frame = self._primary.daily_history(symbol, completed_before)
            if self._valid_daily(frame):
                return frame
        except Exception:
            pass
        return self._fallback.daily_history(symbol, completed_before)

    @staticmethod
    def _quote_rank(quote: PremarketQuote) -> tuple[int, float]:
        status_rank = {
            QuoteStatus.OK: 3,
            QuoteStatus.STALE: 2,
            QuoteStatus.MISSING: 1,
            QuoteStatus.ERROR: 0,
        }
        timestamp = quote.observed_at.timestamp() if quote.observed_at is not None else float("-inf")
        return status_rank.get(quote.status, 0), timestamp

    def premarket_quote(self, symbol: str, now: datetime) -> PremarketQuote:
        try:
            primary = self._primary.premarket_quote(symbol, now)
        except Exception as exc:
            primary = PremarketQuote(symbol, QuoteStatus.ERROR, None, None, type(exc).__name__)
        if primary.status == QuoteStatus.OK:
            return primary
        try:
            fallback = self._fallback.premarket_quote(symbol, now)
        except Exception as exc:
            fallback = PremarketQuote(symbol, QuoteStatus.ERROR, None, None, type(exc).__name__)
        return max((primary, fallback), key=self._quote_rank)


class YahooMarketData:
    def __init__(
        self,
        *,
        ticker_factory: Callable[[str], object] = yf.Ticker,
        sleep: Callable[[float], None] = time.sleep,
        stale_minutes: int = 15,
        calendar=None,
    ):
        self._ticker_factory = ticker_factory
        self._sleep = sleep
        self._stale_minutes = stale_minutes
        self._calendar = calendar or xcals.get_calendar("XNYS")

    def _history(self, symbol: str, *, require_nonempty: bool = False, **kwargs) -> pd.DataFrame:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                frame = self._ticker_factory(symbol).history(timeout=10, **kwargs)
                if require_nonempty and frame.empty:
                    raise ValueError("empty provider response")
                return frame
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
            require_nonempty=True,
        )
        missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
        if missing:
            raise MarketDataError(f"{symbol}: missing columns {', '.join(missing)}")
        result = frame.loc[pd.DatetimeIndex(frame.index).date < completed_before.date(), list(REQUIRED_COLUMNS)]
        result = result.dropna(subset=list(REQUIRED_COLUMNS)).copy()
        if result.empty:
            raise MarketDataError(f"{symbol}: no usable daily data")
        current_label = pd.Timestamp(completed_before.date())
        expected = self._calendar.previous_session(current_label).date()
        if pd.Timestamp(result.index[-1]).date() != expected:
            raise MarketDataError(f"{symbol}: latest bar is not the previous session")
        return result

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
        index = pd.DatetimeIndex(frame.index)
        if index.tz is None:
            index = index.tz_localize(now.tzinfo)
        else:
            index = index.tz_convert(now.tzinfo)
        local_time = index.time
        valid = (
            (index.date == now.date())
            & (index <= pd.Timestamp(now))
            & (local_time >= datetime.strptime("04:00", "%H:%M").time())
            & (local_time < datetime.strptime("09:30", "%H:%M").time())
        )
        closes = frame.loc[valid, "Close"].dropna()
        if closes.empty:
            return PremarketQuote(symbol, QuoteStatus.MISSING, None, None, "no premarket quote")
        observed = pd.Timestamp(closes.index[-1]).to_pydatetime()
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=now.tzinfo)
        age_minutes = (now - observed.astimezone(now.tzinfo)).total_seconds() / 60
        status = QuoteStatus.STALE if age_minutes > self._stale_minutes else QuoteStatus.OK
        return PremarketQuote(symbol, status, float(closes.iloc[-1]), observed)
