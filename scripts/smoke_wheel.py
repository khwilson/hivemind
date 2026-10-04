"""Exercise the distributable with uvx, outside the source checkout."""

import json
import subprocess
import tempfile
import tomllib
from pathlib import Path


def main() -> None:
    source = Path(__file__).resolve().parents[1]
    version = tomllib.loads((source / "pyproject.toml").read_text())["project"][
        "version"
    ]
    wheel = source / f"dist/hivemind-{version}-py3-none-any.whl"
    with tempfile.TemporaryDirectory(prefix="hivemind-wheel-") as temporary:
        root = Path(temporary)
        command = [
            "uvx",
            "--reinstall-package",
            "hivemind",
            "--from",
            str(wheel),
            "hivemind",
            "--path",
            str(root),
        ]
        result = subprocess.run(
            command
            + [
                "init",
                "--repo",
                "example/math",
                "--maintainer-id",
                "1",
                "--required-check",
                "quality:42",
                "--code-owner",
                "trusted-owner",
                "--profile",
                "mathematics",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        assert json.loads(result.stdout)["changed"]
        result = subprocess.run(
            command + ["init", "--repo", "example/math"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        assert json.loads(result.stdout)["changed"] == []
        result = subprocess.run(
            command + ["doctor", "--local"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        assert json.loads(result.stdout)["status"] == "local-valid"
        assert len(list((root / ".hivemind/skills").glob("*/SKILL.md"))) == 5
        result = subprocess.run(
            command + ["ui", "--help"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "--no-browser" in result.stdout
        result = subprocess.run(
            [
                "uvx",
                "--from",
                str(wheel),
                "--",
                "python",
                "-c",
                "from importlib.resources import files; "
                "from hivemind.ui import create_app; "
                "assert 'Background commands' in files('hivemind.web').joinpath('app.js').read_text(); "
                "assert files('hivemind.web').joinpath('style.css').read_bytes()",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        print(
            "Wheel smoke passed: initialization, repeatability, diagnostics, skills, and local UI assets."
        )


if __name__ == "__main__":
    main()
