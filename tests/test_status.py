import json

import pytest
from typer.testing import CliRunner

from hivemind.cli import app
from hivemind.github_client import ApiError


@pytest.fixture
def snapshot():
    tasks = [
        {
            "id": str(i),
            "title": title,
            "priority": 1,
            "status": state,
            "revision": 2,
            "agent": "worker" if state == "active" else None,
            "dependencies": ["1"] if blocked else [],
            "blocked_by": ["1"] if blocked else [],
        }
        for i, (title, state, blocked) in enumerate(
            [
                ("First proof", "active", False),
                ("Second proof", "queued", False),
                ("Dependent proof", "queued", True),
                ("[red]Literal title[/red]", "done", False),
            ],
            start=1,
        )
    ]
    return {
        "agents": [{"id": "worker", "name": "Alice"}],
        "projects": [{"id": "math", "revision": 7, "tasks": tasks}],
    }


@pytest.mark.parametrize(
    "args",
    [
        ["--repo", "owner/math", "status"],
        ["status", "--repo", "owner/math"],
        ["--repo", "other/repo", "status", "--repo", "owner/math"],
    ],
)
def test_status_repo_order_and_json(monkeypatch, tmp_path, snapshot, args):
    class API:
        def json_file(self, repo, path, ref):
            assert (repo, path, ref) == ("owner/math", "index.json", "hivemind-state")
            return snapshot

    monkeypatch.setattr("hivemind.client.GitHub", API)
    for output_args in ([], ["--json"]):
        result = CliRunner().invoke(app, ["--path", str(tmp_path), *args, *output_args])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == snapshot


def test_pretty_status_handles_states_and_literal_text(monkeypatch, snapshot):
    class API:
        def json_file(self, repo, path, ref):
            return snapshot

    monkeypatch.setattr("hivemind.client.GitHub", API)
    result = CliRunner().invoke(
        app, ["status", "--repo", "owner/math", "--pretty"], env={"COLUMNS": "180"}
    )
    assert result.exit_code == 0, result.output
    for text in (
        "owner/math",
        "queue revision 7",
        "Alice",
        "First proof",
        "[red]Literal title[/red]",
        "1 active, 1 ready, 1 blocked, 1 done, 0 cancelled",
    ):
        assert text in result.output


def test_status_empty_queue_and_api_error(monkeypatch):
    class API:
        def json_file(self, repo, path, ref):
            return {"projects": [{"id": "math", "tasks": []}]}

    monkeypatch.setattr("hivemind.client.GitHub", API)
    args = ["status", "--repo", "owner/math", "--pretty"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0
    assert "No tasks yet." in result.output

    def fail(self, repo, path, ref):
        raise ApiError(403, "Forbidden")

    monkeypatch.setattr(API, "json_file", fail)
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 1
    assert "GitHub 403" in result.output
    assert "No tasks yet." not in result.output


def test_status_rejects_conflicting_formats():
    result = CliRunner().invoke(app, ["status", "--json", "--pretty"])
    assert result.exit_code != 0
    assert "Choose either --json or --pretty" in result.output
