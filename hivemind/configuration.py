"""Protected repository configuration, separate from broker-owned queue state."""

import tomllib
from pathlib import Path

import tomlkit

from .models import Settings

CONFIG = "hivemind.toml"


def parse_settings(text: str) -> Settings:
    return Settings.model_validate(tomllib.loads(text))


def serialize_settings(settings: Settings) -> str:
    return (
        "# Trusted configuration: review changes on the default branch.\n"
        + tomlkit.dumps(settings.model_dump())
    )


def write_agents(path: Path, settings: Settings) -> None:
    """Only change registry entries; preserve other settings and comments."""
    document = tomlkit.parse(path.read_text())
    registry = document.get("agents")
    if registry is None or not settings.agents:
        document["agents"] = [agent.model_dump() for agent in settings.agents]
    elif len(registry) == 0:
        document["agents"] = [agent.model_dump() for agent in settings.agents]
    else:
        for agent in settings.agents:
            existing = next(
                (entry for entry in registry if entry["id"] == agent.id), None
            )
            if existing is None:
                registry.append(tomlkit.item(agent.model_dump()))
            elif existing.get("revoked", False) != agent.revoked:
                existing["revoked"] = agent.revoked
    text = tomlkit.dumps(document)
    if parse_settings(text) != settings:
        raise ValueError("Registry edit would change other configuration")
    path.write_text(text)
