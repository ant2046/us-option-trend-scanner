from pathlib import Path

import yaml


def test_validation_workflow_only_runs_dry_and_archives_failures():
    workflow = yaml.load(Path(".github/workflows/premarket-scan.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert workflow["on"]["schedule"] == [{"cron": "30 8 * * 1-5", "timezone": "America/New_York"}]
    steps = workflow["jobs"]["scan"]["steps"]
    dry = next(step for step in steps if step.get("name") == "Validation dry run")
    assert dry["env"] == {"MASSIVE_API_KEY": "${{ secrets.MASSIVE_API_KEY }}"}
    assert all("--send" not in step.get("run", "") for step in steps)
    archive = next(step for step in steps if step.get("name") == "Archive scan")
    assert archive["if"] == "always()"
    assert archive["with"]["path"] in dry["run"]
    replay = next(step for step in steps if step.get("name") == "Historical dry run")
    assert replay["env"] == dry["env"]
    assert "workflow_dispatch" in replay["if"]
