from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from .models import MarketSession


NEW_YORK = ZoneInfo("America/New_York")


class MarketSessionService:
    def __init__(self, calendar=None):
        self._calendar = calendar or xcals.get_calendar("XNYS")

    def session_for(self, value: date) -> MarketSession | None:
        label = pd.Timestamp(value)
        if not self._calendar.is_session(label):
            return None
        opens_at = self._calendar.session_open(label).to_pydatetime().astimezone(NEW_YORK)
        return MarketSession(session_date=value, opens_at=opens_at)

