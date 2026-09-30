from pathlib import Path

import pytest

from hivemind.models import Agent, CheckPolicy, ProjectConfig, Settings
from hivemind.signing import generate


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    key = generate(tmp_path / "key.pem")
    return Settings(
        hub="owner/math",
        maintainers=[1],
        projects=[
            ProjectConfig(
                id="math",
                name="Math",
                repo="owner/math",
                required_checks=[CheckPolicy(name="quality", app_id=42)],
            )
        ],
        agents=[
            Agent(
                id=key["id"],
                name="Agent",
                github_id=2,
                public_key=key["public_key"],
                projects=["math"],
            )
        ],
    )
