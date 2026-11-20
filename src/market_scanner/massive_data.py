from __future__ import annotations

from datetime import datetime, time, timedelta

import exchange_calendars as xcals
import pandas as pd

from .data import MarketDataError, REQUIRED_COLUMNS
from .models import PremarketQuote, QuoteStatus


class MassiveMarketData:
    def __init__(self, client, *, stale_minutes: int = 15, calendar=None):
        self._client = client
        self._stale_minutes = stale_minutes
        self._calendar = calendar or xcals.get_calendar("XNYS")

    @staticmethod
    def _frame(results, timezone) -> pd.DataFrame:
        if not results:
            return pd.DataFrame(
                columns=REQUIRED_COLUMNS,
                index=pd.DatetimeIndex([], tz=timezone, name="Timestamp"),
            )
        rows = []
        for item in results:
            required = ("o", "h", "l", "c", "v", "t")
            if not isinstance(item, dict) or any(key not in item for key in required):
                raise MarketDataError("malformed Massive aggregate")
            try:
                observed = pd.to_datetime(item["t"], unit="ms", utc=True).tz_convert(timezone)
                values = [float(item[key]) for key in ("o", "h", "l", "c", "v")]
            except (TypeError, ValueError, OverflowError) as exc:
                raise MarketDataError("malformed Massive aggregate") from exc
            rows.append((observed, *values))
        frame = pd.DataFrame(rows, columns=("Timestamp", *REQUIRED_COLUMNS)).set_index("Timestamp")
        return frame.sort_index()

    def daily_history(self, symbol: str, completed_before: datetime) -> pd.DataFrame:
        end = completed_before.date()
        start = end - timedelta(days=200)
        try:
            results = self._client.get(
                f"/v2/aggs/ticker/{symbol}/range/1/day/{start.isoformat()}/{end.isoformat()}",
                {"adjusted": "true", "sort": "asc", "limit": 50000},
                paginate=True,
            )
            frame = self._frame(results, completed_before.tzinfo)
        except MarketDataError:
            raise
        except Exception as exc:
            raise MarketDataError(f"{symbol}: Massive daily request failed") from exc
        result = frame.loc[frame.index.date < completed_before.date(), list(REQUIRED_COLUMNS)]
        result = result.dropna(subset=list(REQUIRED_COLUMNS)).copy()
        if result.empty:
            raise MarketDataError(f"{symbol}: no usable daily data")
        expected = self._calendar.previous_session(pd.Timestamp(completed_before.date())).date()
        if result.index[-1].date() != expected:
            raise MarketDataError(f"{symbol}: latest bar is not the previous session")
        return result

    def premarket_quote(self, symbol: str, now: datetime) -> PremarketQuote:
        date = now.date().isoformat()
        try:
            results = self._client.get(
                f"/v2/aggs/ticker/{symbol}/range/1/minute/{date}/{date}",
                {"adjusted": "true", "sort": "asc", "limit": 50000},
                paginate=True,
            )
            frame = self._frame(results, now.tzinfo)
        except Exception as exc:
            return PremarketQuote(symbol, QuoteStatus.ERROR, None, None, type(exc).__name__)
        if frame.empty:
            return PremarketQuote(symbol, QuoteStatus.MISSING, None, None, "no premarket quote")
        valid = (
            (frame.index.date == now.date())
            & (frame.index <= pd.Timestamp(now))
            & (frame.index.time >= time(4, 0))
            & (frame.index.time < time(9, 30))
        )
        closes = frame.loc[valid, "Close"].dropna()
        if closes.empty:
            return PremarketQuote(symbol, QuoteStatus.MISSING, None, None, "no premarket quote")
        observed = closes.index[-1].to_pydatetime()
        age_minutes = (now - observed).total_seconds() / 60
        status = QuoteStatus.STALE if age_minutes > self._stale_minutes else QuoteStatus.OK
        return PremarketQuote(symbol, status, float(closes.iloc[-1]), observed)
