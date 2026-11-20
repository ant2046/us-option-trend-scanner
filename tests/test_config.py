import pytest

from market_scanner.config import ConfigError, Settings, SYMBOLS


def test_symbols_and_default_thresholds_are_fixed(monkeypatch):
    monkeypatch.delenv("WECOM_WEBHOOK_URL", raising=False)

    settings = Settings.from_env(require_webhook=False)

    assert SYMBOLS == (
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
    assert settings.ma_short == 20
    assert settings.ma_long == 50
    assert settings.slope_lookback == 5
    assert settings.breakout_lookback == 10
    assert settings.pullback_band == pytest.approx(0.02)
    assert settings.breakout_volume_ratio == pytest.approx(1.2)
    assert settings.gap_limit == pytest.approx(0.03)
    assert settings.earnings_warning_days == 3
    assert settings.option_expiry_min_days == 14
    assert settings.option_expiry_max_days == 45
    assert settings.option_max_spread_ratio == pytest.approx(0.10)
    assert settings.option_min_volume == 100
    assert settings.option_min_open_interest == 500
    assert settings.enrichment_timeout_seconds == 60
    assert settings.provider_timeout_seconds == 10
    assert settings.enrichment_workers == 4
    assert settings.normalized_score_min_completeness == pytest.approx(0.70)


def test_send_mode_requires_webhook(monkeypatch):
    monkeypatch.delenv("WECOM_WEBHOOK_URL", raising=False)

    with pytest.raises(ConfigError, match="WECOM_WEBHOOK_URL"):
        Settings.from_env(require_webhook=True)


def test_dry_run_does_not_require_webhook(monkeypatch):
    monkeypatch.delenv("WECOM_WEBHOOK_URL", raising=False)

    assert Settings.from_env(require_webhook=False).wecom_webhook_url is None


def test_settings_repr_redacts_webhook(monkeypatch):
    secret = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=super-secret"
    monkeypatch.setenv("WECOM_WEBHOOK_URL", secret)

    settings = Settings.from_env(require_webhook=True)

    assert secret not in repr(settings)
    assert "super-secret" not in repr(settings)


def test_massive_configuration_is_optional_and_redacted(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    monkeypatch.delenv("MASSIVE_BASE_URL", raising=False)

    missing = Settings.from_env(require_webhook=False)

    assert missing.massive_api_key is None
    assert missing.massive_base_url == "https://api.massive.com"

    monkeypatch.setenv("MASSIVE_API_KEY", "massive-secret")
    monkeypatch.setenv("MASSIVE_BASE_URL", "https://example.invalid/")

    configured = Settings.from_env(require_webhook=False)

    assert configured.massive_api_key == "massive-secret"
    assert configured.massive_base_url == "https://example.invalid"
    assert "massive-secret" not in repr(configured)
