from pathlib import Path


WORKFLOW = Path(".github/workflows/premarket-scan.yml")


def test_workflow_has_safe_schedule_and_manual_defaults():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'cron: "30 8 * * 1-5"' in text
    assert 'timezone: "America/New_York"' in text
    assert 'python-version: "3.12"' in text
    assert "default: false" in text
    assert "python -m market_scanner.main --send" in text
    assert "python -m market_scanner.main --dry-run" in text
    assert "concurrency:" in text


def test_webhook_only_comes_from_github_secret():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets.WECOM_WEBHOOK_URL" in text
    assert "qyapi.weixin.qq.com" not in text
