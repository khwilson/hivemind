import json

import pytest
from typer.testing import CliRunner

from hivemind.cli import app
from hivemind.github_client import ApiError
from hivemind.installation import initialize
from hivemind.models import CheckPolicy


@pytest.mark.parametrize("local", [False, True])
def test_kick_uses_live_default_branch(monkeypatch, tmp_path, local):
    calls = []

    class API:
        def get(self, path):
            if path == "/repos/owner/math":
                return {"default_branch": "trunk"}
            return {"state": "active"}

        def request(self, path, method, data):
            calls.append((path, method, data))
            return {"html_url": "https://github.com/owner/math/actions/runs/123"}

    monkeypatch.setattr("hivemind.client.GitHub", API)
    args = ["--path", str(tmp_path)]
    if local:
        initialize(tmp_path, "owner/math", [1], [CheckPolicy(name="test", app_id=42)])
    else:
        args += ["--repo", "owner/math"]
    result = CliRunner().invoke(app, [*args, "kick"])
    assert result.exit_code == 0, result.output
    assert calls == [
        (
            "/repos/owner/math/actions/workflows/hivemind-broker.yml/dispatches",
            "POST",
            {"ref": "trunk"},
        )
    ]
    assert json.loads(result.output)["status"] == "dispatched"
    assert json.loads(result.output)["url"].endswith("/123")


@pytest.mark.parametrize("disabled", [False, True])
def test_kick_reports_permission_and_disabled_workflows(monkeypatch, disabled):
    class API:
        def get(self, path):
            if path == "/repos/owner/math":
                return {"default_branch": "main"}
            return {"state": "disabled_manually" if disabled else "active"}

        def request(self, path, method, data):
            assert not disabled, "Disabled workflows must not be dispatched"
            raise ApiError(403, "Resource not accessible by personal access token")

    monkeypatch.setattr("hivemind.client.GitHub", API)
    result = CliRunner().invoke(app, ["--repo", "owner/math", "kick"])
    assert result.exit_code == 1
    assert ("disabled" if disabled else "Actions write") in result.output
    assert '"status": "dispatched"' not in result.output
