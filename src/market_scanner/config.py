from __future__ import annotations

import os
from dataclasses import dataclass, field


SYMBOLS = (
    "SPY",
    "QQQ",
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "NVDA",
    "META",
    "TSLA",
)


class ConfigError(ValueError):
    """Raised when required runtime configuration is missing."""


@dataclass(frozen=True)
class Settings:
    symbols: tuple[str, ...] = SYMBOLS
    ma_short: int = 20
    ma_long: int = 50
    slope_lookback: int = 5
    breakout_lookback: int = 10
    pullback_band: float = 0.02
    breakout_volume_ratio: float = 1.2
    gap_limit: float = 0.03
    quote_stale_minutes: int = 15
    wecom_webhook_url: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, *, require_webhook: bool) -> "Settings":
        webhook = os.getenv("WECOM_WEBHOOK_URL") or None
        if require_webhook and not webhook:
            raise ConfigError("WECOM_WEBHOOK_URL is required in send mode")
        return cls(wecom_webhook_url=webhook)

