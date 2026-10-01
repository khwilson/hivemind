import json

import pytest
from typer.testing import CliRunner

from hivemind.cli import app
from hivemind.configuration import parse_settings, serialize_settings, write_agents
from hivemind.installation import initialize, read_settings
from hivemind.models import CheckPolicy


def test_registry_preserves_comments_and_policy(tmp_path, settings):
    path = tmp_path / "hivemind.toml"
    text = "# Maintainer rationale\n" + serialize_settings(settings)
    text = text.replace(
        'state_branch = "hivemind-state"', 'state_branch = "hivemind-state" # protected'
    )
    path.write_text(text)
    settings.agents[0].revoked = True
    write_agents(path, settings)
    assert "# Maintainer rationale" in path.read_text()
    assert "# protected" in path.read_text()
    assert parse_settings(path.read_text()) == settings
    settings.agents.append(
        settings.agents[0].model_copy(update={"id": "a" * 16, "name": "second"})
    )
    write_agents(path, settings)
    assert parse_settings(path.read_text()) == settings


def test_empty_registry_registration(tmp_path, settings):
    path = tmp_path / "hivemind.toml"
    initial = settings.model_copy(update={"agents": []})
    path.write_text(serialize_settings(initial))
    write_agents(path, settings)
    assert parse_settings(path.read_text()) == settings


def test_upgrade_migrates_legacy_config_without_deleting_it(tmp_path, settings):
    initialize(tmp_path, settings.hub, [1], [CheckPolicy(name="quality", app_id=42)])
    path = tmp_path / "hivemind.toml"
    path.unlink()
    legacy = tmp_path / ".hivemind/config.json"
    data = settings.model_dump(exclude={"standard_work"})
    legacy.write_text(json.dumps(data))
    standard = tmp_path / ".hivemind/standard-work.json"
    standard.write_text(
        json.dumps(
            {
                "version": 1,
                "rules": [
                    {
                        "id": "custom",
                        "version": 3,
                        "paths": ["*.tex"],
                        "skill": "mathematics-review",
                    }
                ],
            }
        )
    )
    original = legacy.read_bytes(), standard.read_bytes()
    result = CliRunner().invoke(app, ["--path", str(tmp_path), "upgrade"])
    assert result.exit_code == 0, result.output
    assert read_settings(tmp_path).agents == settings.agents
    assert read_settings(tmp_path).standard_work.rules[0].id == "custom"
    assert (legacy.read_bytes(), standard.read_bytes()) == original
    assert not (tmp_path / ".hivemind/project.json").exists()


def test_unknown_policy_field_is_rejected(settings):
    with pytest.raises(ValueError):
        parse_settings(serialize_settings(settings) + "\n[untrusted]\nbypass = true\n")
