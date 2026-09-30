from pathlib import Path

import pytest

from hivemind.github import ApiError, GitHub
from hivemind.installation import apply_setup, initialize, read_settings
from hivemind.models import CheckPolicy


class SetupAPI(GitHub):
    def __init__(self, root: Path, extra_policy=False):
        super().__init__("")
        self.root = root
        self.extra_policy = extra_policy
        self.writes = []
        self.state_exists = False
        self.rulesets = []
        self.policies = []
        self.variables = []

    def get(self, path):
        if path == "/repos/owner/math":
            return {"id": 7, "default_branch": "main", "permissions": {"admin": True}}
        if "/commits/main" in path:
            return {"sha": "a" * 40}
        if "/git/ref/" in path:
            raise ApiError(404, "not created")
        if "/environments/coordination" in path:
            return {}
        raise AssertionError(path)

    def json_file(self, repo, path, ref):
        import json

        return json.loads((self.root / path).read_text())

    def text_file(self, repo, path, ref):
        return (self.root / path).read_text()

    def pages(self, path, key=None):
        if "/rulesets" in path:
            return self.rulesets
        if "/deployment-branch-policies" in path:
            return (
                [{"name": "*", "type": "branch"}]
                if self.extra_policy
                else self.policies
            )
        if "/variables" in path:
            return self.variables
        raise AssertionError(path)

    def request(self, path, method="GET", data=None):
        self.writes.append((path, method, data))
        if "/git/trees" in path or "/git/commits" in path:
            return {"sha": "b" * 40}
        return {}


def installation(root):
    initialize(
        root,
        "owner/math",
        [1],
        [CheckPolicy(name="quality", app_id=42)],
        code_owner="owner",
    )


def test_setup_checks_existing_unsafe_environment_before_mutation(tmp_path):
    installation(tmp_path)
    api = SetupAPI(tmp_path, extra_policy=True)
    with pytest.raises(ValueError, match="other branch/tag"):
        apply_setup(tmp_path, api, 99, "Iv1.client")
    assert api.writes == []


def test_setup_initializes_state_before_restricting_creation(tmp_path):
    installation(tmp_path)
    api = SetupAPI(tmp_path)
    result = apply_setup(tmp_path, api, 99, "Iv1.client")
    assert result["status"] == "settings-applied"
    state_index = next(
        i for i, (path, _, _) in enumerate(api.writes) if path.endswith("/git/refs")
    )
    rules_index = next(
        i for i, (path, _, _) in enumerate(api.writes) if path.endswith("/rulesets")
    )
    assert state_index < rules_index
    assert api.writes[-1][2]["value"] == "Iv1.client"
    assert read_settings(tmp_path).hub == "owner/math"
