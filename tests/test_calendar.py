from datetime import date

from market_scanner.calendar import MarketSessionService


def test_regular_session_has_new_york_open_time():
    session = MarketSessionService().session_for(date(2026, 11, 19))

    assert session is not None
    assert session.session_date == date(2026, 11, 19)
    assert session.opens_at.tzinfo is not None
    assert session.opens_at.tzinfo.key == "America/New_York"
    assert (session.opens_at.hour, session.opens_at.minute) == (9, 30)


def test_weekend_and_nyse_holiday_are_closed():
    service = MarketSessionService()

    assert service.session_for(date(2026, 11, 21)) is None
    assert service.session_for(date(2026, 12, 25)) is None

