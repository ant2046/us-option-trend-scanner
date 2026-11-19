import numpy as np
import pandas as pd

from market_scanner.signals import SignalEngine


def make_bars(count=70, start=100.0, step=0.5):
    close = start + np.arange(count) * step
    index = pd.bdate_range("2026-07-01", periods=count)
    return pd.DataFrame(
        {
            "Open": close - 0.2,
            "High": close + 0.8,
            "Low": close - 0.8,
            "Close": close,
            "Volume": np.full(count, 1000.0),
        },
        index=index,
    )


def test_rejects_insufficient_or_falling_trend():
    engine = SignalEngine()
    assert engine.evaluate("AAPL", make_bars(59), True) is None

    falling = make_bars(step=-0.5)
    assert engine.evaluate("AAPL", falling, True) is None


def test_pullback_uses_historical_ma_and_sets_invalidation():
    bars = make_bars()
    ma20 = bars["Close"].rolling(20).mean()
    bars.loc[bars.index[-3], "Low"] = ma20.iloc[-3]
    bars.loc[bars.index[-1], "Close"] = bars["High"].iloc[-2] + 1
    bars.loc[bars.index[-1], "High"] = bars["Close"].iloc[-1] + 0.5

    signal = SignalEngine().evaluate("AAPL", bars, True)

    assert signal is not None
    assert "回调转强" in signal.triggers
    assert signal.invalidation == min(bars["Low"].iloc[-5:].min(), signal.ma20)


def test_breakout_excludes_current_bar_and_requires_volume():
    bars = make_bars()
    previous_high = bars["High"].iloc[-11:-1].max()
    bars.loc[bars.index[-1], "Close"] = previous_high + 1
    bars.loc[bars.index[-1], "High"] = previous_high + 1.5
    bars.loc[bars.index[-1], "Volume"] = 1300

    signal = SignalEngine().evaluate("NVDA", bars, True)

    assert signal is not None
    assert "平台突破" in signal.triggers
    assert signal.invalidation == min(previous_high, signal.ma20)

    bars.loc[bars.index[-1], "Volume"] = 1100
    assert SignalEngine().evaluate("NVDA", bars, True) is None


def test_score_counts_four_optional_conditions():
    bars = make_bars()
    previous_high = bars["High"].iloc[-11:-1].max()
    bars.loc[bars.index[-1], ["Close", "High", "Volume"]] = [
        previous_high + 1,
        previous_high + 1.5,
        1300,
    ]

    signal = SignalEngine().evaluate("META", bars, True)

    assert signal is not None
    assert signal.score == 4


def test_nan_rows_do_not_count_toward_minimum_history():
    bars = make_bars(65)
    bars.loc[bars.index[:6], "Close"] = np.nan

    assert SignalEngine().evaluate("AAPL", bars, True) is None
