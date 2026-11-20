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
    earnings_warning_days: int = 3
    option_expiry_min_days: int = 14
    option_expiry_max_days: int = 45
    option_max_spread_ratio: float = 0.10
    option_min_volume: int = 100
    option_min_open_interest: int = 500
    enrichment_timeout_seconds: int = 60
    provider_timeout_seconds: int = 10
    provider_retries: int = 1
    enrichment_workers: int = 4
    normalized_score_min_completeness: float = 0.70
    wecom_webhook_url: str | None = field(default=None, repr=False)
    massive_api_key: str | None = field(default=None, repr=False)
    massive_base_url: str = "https://api.massive.com"

    @classmethod
    def from_env(cls, *, require_webhook: bool) -> "Settings":
        webhook = os.getenv("WECOM_WEBHOOK_URL") or None
        massive_api_key = os.getenv("MASSIVE_API_KEY") or None
        massive_base_url = (os.getenv("MASSIVE_BASE_URL") or "https://api.massive.com").rstrip("/")
        if require_webhook and not webhook:
            raise ConfigError("WECOM_WEBHOOK_URL is required in send mode")
        return cls(
            wecom_webhook_url=webhook,
            massive_api_key=massive_api_key,
            massive_base_url=massive_base_url,
        )

