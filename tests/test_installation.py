import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hivemind.cli import app
from hivemind.doctor import doctor
from hivemind.installation import initialize
from hivemind.models import CheckPolicy


def install(root: Path, **kwargs):
    return initialize(
        root,
        "owner/math",
        [1],
        [CheckPolicy(name="quality", app_id=42)],
        profile="mathematics",
        **kwargs,
    )


def test_repeatable_installation_preserves_existing_rules(tmp_path):
    original = "# Local rules\n\nUse Lean.\n"
    (tmp_path / "AGENTS.md").write_text(original)
    result = install(tmp_path)
    assert not result["conflicts"]
    assert (tmp_path / "AGENTS.md").read_text().startswith(original.strip())
    before = {
        p.relative_to(tmp_path): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    second = install(tmp_path)
    after = {
        p.relative_to(tmp_path): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    assert not second["changed"]
    assert before == after
    assert doctor(tmp_path)["status"] == "local-valid"
    rules = json.loads((tmp_path / ".hivemind/standard-work.json").read_text())
    assert rules["rules"][0]["enabled"]


def test_custom_skill_is_preserved_and_reported(tmp_path):
    install(tmp_path)
    skill = tmp_path / ".hivemind/skills/mathematics-generalization/SKILL.md"
    skill.write_text(skill.read_text() + "\nOur custom theorem convention.\n")
    result = install(tmp_path)
    assert ".hivemind/skills/mathematics-generalization/SKILL.md" in result["conflicts"]
    assert "Our custom theorem convention." in skill.read_text()


def test_dry_run_and_malformed_markers_do_not_write(tmp_path):
    result = install(tmp_path, dry_run=True)
    assert result["changed"]
    assert not list(tmp_path.iterdir())
    (tmp_path / "AGENTS.md").write_text("<!-- hivemind:start --> broken")
    with pytest.raises(ValueError, match="markers"):
        install(tmp_path)
    assert not (tmp_path / ".hivemind").exists()


def test_symlink_escape_is_rejected_before_writes(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "checkout"
    root.mkdir()
    (root / ".hivemind").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="inside checkout"):
        install(root)
    assert not list(outside.iterdir())
    assert not (root / "AGENTS.md").exists()


def test_cli_init_upgrade_doctor_and_keygen(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--path",
            str(tmp_path),
            "init",
            "--repo",
            "owner/math",
            "--maintainer-id",
            "1",
            "--required-check",
            "quality:42",
            "--profile",
            "mathematics",
        ],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["--path", str(tmp_path), "upgrade"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["--path", str(tmp_path), "doctor", "--local"])
    assert result.exit_code == 0, result.output
    key = tmp_path / "private.pem"
    result = runner.invoke(app, ["keygen", "--out", str(key)])
    assert result.exit_code == 0, result.output
    assert key.stat().st_mode & 0o777 == 0o600
    assert runner.invoke(app, ["keygen", "--out", str(key)]).exit_code == 1


def test_cli_setup_plan_has_separate_history_rules(tmp_path):
    install(tmp_path)
    result = CliRunner().invoke(
        app, ["--path", str(tmp_path), "setup", "--app-id", "99"]
    )
    assert result.exit_code == 0, result.output
    plan = json.loads(result.output)
    access, history, default = plan["rulesets"]
    assert access["bypass_actors"][0]["actor_id"] == 99
    assert history["bypass_actors"] == []
    assert default["bypass_actors"] == []
    assert plan["branch_policy"] == {"name": "main", "type": "branch"}


def test_repeat_init_without_profile_preserves_installed_selection(tmp_path):
    install(tmp_path)
    result = initialize(tmp_path, "owner/math", [], [])
    assert result["changed"] == []
    assert (
        json.loads((tmp_path / ".hivemind/templates.json").read_text())["profile"]
        == "mathematics"
    )


def test_nested_directory_escape_is_checked_before_any_install_writes(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / ".hivemind").mkdir()
    (root / ".hivemind/hints").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="inside checkout"):
        install(root)
    assert not (root / "AGENTS.md").exists()
    assert not (root / ".hivemind/config.json").exists()
