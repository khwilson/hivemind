import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from hivemind.cli import app as cli
from hivemind.ui import Command, Runner, command_args, create_app

TASK = "a" * 12
OTHER = "b" * 12


class FakeRunner(Runner):
    def __init__(self):
        super().__init__(Path("."), "owner/math")
        self.calls = []
        self.receipt_status = "pending"

    def run(self, arguments, project=None):
        self.calls.append((arguments, project))
        if arguments == ["status", "--json"]:
            return {"projects": [], "agents": []}
        if arguments == ["whoami"]:
            return {"id": 1, "login": "owner"}
        if arguments[:2] == ["request", "show"]:
            return {
                "status": self.receipt_status,
                "request_id": arguments[2],
                "message": "Revision conflict",
            }
        return {
            "status": "pending",
            "request_id": "c" * 32,
            "url": "https://github.com/owner/math/issues/1",
        }


@pytest.fixture
def client():
    runner = FakeRunner()
    with TestClient(
        create_app(runner, "session", 8765),
        base_url="http://127.0.0.1:8765",
        headers={"X-Hivemind-Session": "session"},
    ) as http:
        yield http, runner


def command(action="add", args=None):
    return {
        "id": "d" * 32,
        "project": "math",
        "action": action,
        "args": args or {"title": "Proof", "criteria": "Pass Lean"},
    }


def test_state_and_static_assets_use_cli(client):
    http, runner = client
    result = http.get("/api/state")
    assert result.status_code == 200
    assert result.json()["actor"]["login"] == "owner"
    assert runner.calls == [(["status", "--json"], None), (["whoami"], None)]
    for path in ("/", "/app.js", "/style.css"):
        response = http.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert http.get("/../pyproject.toml").status_code == 404


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Hivemind-Session": "wrong"},
        {"Origin": "https://evil.example"},
        {"Origin": "http://localhost:8765"},
        {"Host": "evil.example:8765"},
    ],
)
def test_local_boundary_rejects_requests_before_commands(client, headers):
    http, runner = client
    response = http.post("/api/commands", json=command(), headers=headers)
    assert response.status_code == 403
    assert not runner.calls


def test_pending_receipts_rejection_and_duplicate_submission(client):
    http, runner = client
    body = command()
    assert http.post("/api/commands", json=body).status_code == 202
    assert http.post("/api/commands", json=body).status_code == 202
    assert len(runner.calls) == 1
    job = http.get("/api/jobs/" + body["id"]).json()
    assert job["status"] == "finished"
    assert job["result"]["status"] == "pending"
    assert http.get("/api/requests/" + "c" * 32).json()["status"] == "pending"
    runner.receipt_status = "rejected"
    receipt = http.get("/api/requests/" + "c" * 32).json()
    assert receipt["status"] == "rejected"
    assert receipt["message"] == "Revision conflict"
    body["args"]["title"] = "Changed"
    assert http.post("/api/commands", json=body).status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        command("setup"),
        {**command(), "shell": "rm -rf /"},
        command("edit", {"task": TASK, "title": "Changed"}),
        command("cancel", {"task": "--help", "expected_revision": 1}),
    ],
)
def test_disallowed_commands_and_missing_revisions_never_run(client, body):
    http, runner = client
    assert http.post("/api/commands", json=body).status_code in (400, 422)
    assert not runner.calls


def test_edits_and_reordering_preserve_expected_revisions():
    edit = Command.model_validate(
        command(
            "edit",
            {
                "task": TASK,
                "expected_revision": 7,
                "parent": None,
                "dependencies": [],
                "priority": 1,
                "release_claim": True,
            },
        )
    )
    args = command_args(edit)
    assert args[:3] == ["task", "edit", TASK]
    assert args[args.index("--revision") + 1] == "7"
    assert "--clear-parent" in args
    assert "--clear-dependencies" in args
    assert "--release-claim" in args
    order = Command.model_validate(
        command("prioritize", {"tasks": [OTHER, TASK], "expected_revision": 9})
    )
    assert command_args(order) == ["task", "prioritize", OTHER, TASK, "--revision", "9"]


def test_subprocess_uses_fixed_repo_and_no_shell_or_signing_key(monkeypatch, tmp_path):
    monkeypatch.setenv("HIVEMIND_KEY", "private.pem")
    monkeypatch.setenv("HIVEMIND_REPO", "wrong/repo")
    monkeypatch.setenv("GH_TOKEN", "local-token")
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv, 0, json.dumps({"status": "pending"}), ""
        )

    monkeypatch.setattr(subprocess, "run", run)
    runner = Runner(tmp_path, "owner/math")
    assert (
        runner.run(
            ["task", "add", "--title", "$(echo injected)", "--criteria", "Proof"],
            "math",
        )["status"]
        == "pending"
    )
    argv, options = calls[0]
    assert argv[1:4] == ["-I", "-m", "hivemind.cli"]
    assert "owner/math" in argv and "wrong/repo" not in argv
    assert "$(echo injected)" in argv
    assert "shell" not in options
    assert "HIVEMIND_KEY" not in options["env"]
    assert options["env"]["GH_TOKEN"] == "local-token"
    assert options["timeout"] == 90


def test_rejected_cli_receipt_remains_machine_readable(monkeypatch, tmp_path):
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv, 1, '{"status":"rejected","message":"stale revision"}', ""
        )

    monkeypatch.setattr(subprocess, "run", run)
    assert (
        Runner(tmp_path, "owner/math").run(["request", "show", "c" * 32])["status"]
        == "rejected"
    )


@pytest.mark.parametrize(
    "args", [["--repo", "owner/math", "ui"], ["ui", "--repo", "owner/math"]]
)
def test_ui_cli_launch(monkeypatch, tmp_path, args):
    calls = []
    monkeypatch.setattr("hivemind.ui.serve", lambda *values: calls.append(values))
    result = CliRunner().invoke(
        cli, ["--path", str(tmp_path), *args, "--port", "0", "--no-browser"]
    )
    assert result.exit_code == 0, result.output
    assert calls == [(tmp_path, "owner/math", 0, False)]
