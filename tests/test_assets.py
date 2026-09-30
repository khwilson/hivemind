import re
from importlib.resources import files

import yaml

from hivemind.installation import initialize
from hivemind.models import CheckPolicy


def test_privileged_workflow_runs_trusted_code_and_scopes_credential(tmp_path):
    initialize(tmp_path, "owner/math", [1], [CheckPolicy(name="quality", app_id=42)])
    workflow = yaml.load(
        (tmp_path / ".github/workflows/hivemind-broker.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert "pull_request" not in workflow["on"]
    assert "pull_request_target" not in workflow["on"]
    job = workflow["jobs"]["reconcile"]
    assert job["environment"] == "coordination"
    assert "github.event.repository.default_branch" in job["if"]
    assert workflow["permissions"] == {"contents": "read"}
    for step in job["steps"]:
        if "uses" in step:
            assert re.fullmatch(r"[0-9a-f]{40}", step["uses"].split("@")[1])
        if "run" in step:
            assert "github.event.issue" not in step["run"]
    token = next(s for s in job["steps"] if s.get("id") == "broker-token")
    assert token["with"]["repositories"] == "${{ github.event.repository.name }}"
    assert token["with"]["private-key"] == "${{ secrets.HIVEMIND_APP_PRIVATE_KEY }}"


def test_packaged_skills_have_discoverable_frontmatter():
    for folder in files("hivemind").joinpath("templates/skills").iterdir():
        if not folder.is_dir():
            continue
        text = folder.joinpath("SKILL.md").read_text()
        frontmatter = yaml.safe_load(text.split("---", 2)[1])
        assert frontmatter["name"] == folder.name
        assert frontmatter["description"].strip()
