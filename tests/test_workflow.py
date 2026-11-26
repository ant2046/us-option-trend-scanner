from pathlib import Path

import yaml


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
    assert "github.run_id" in text


def test_workflow_pins_stable_ubuntu_runner():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    assert workflow["jobs"]["scan"]["runs-on"] == "ubuntu-24.04"


def test_webhook_only_comes_from_github_secret():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets.WECOM_WEBHOOK_URL" in text
    assert "qyapi.weixin.qq.com" not in text


def test_workflow_installs_cjk_font_before_sending_image_report():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["scan"]["steps"]
    font_index = next(index for index, step in enumerate(steps) if step.get("name") == "Install CJK font")
    send_index = next(index for index, step in enumerate(steps) if step.get("name") == "Scheduled or explicitly requested send")

    assert "fonts-noto-cjk" in steps[font_index]["run"]
    assert font_index < send_index
    assert steps[send_index]["env"]["WECOM_WEBHOOK_URL"] == "${{ secrets.WECOM_WEBHOOK_URL }}"


def test_scan_steps_receive_massive_secret_but_dry_run_cannot_send():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["scan"]["steps"]
    send = next(step for step in steps if step.get("name") == "Scheduled or explicitly requested send")
    tests = next(step for step in steps if step.get("name") == "Run tests")
    dry_run = next(step for step in steps if step.get("name") == "Manual dry run")

    assert send["env"]["MASSIVE_API_KEY"] == "${{ secrets.MASSIVE_API_KEY }}"
    assert "MASSIVE_API_KEY" not in tests.get("env", {})
    assert dry_run["env"]["MASSIVE_API_KEY"] == "${{ secrets.MASSIVE_API_KEY }}"
    assert "WECOM_WEBHOOK_URL" not in dry_run["env"]
