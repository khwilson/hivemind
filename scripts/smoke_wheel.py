"""Exercise the distributable with uvx, outside the source checkout."""

import json
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    source = Path(__file__).resolve().parents[1]
    wheel = source / "dist/hivemind-0.1.0-py3-none-any.whl"
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
        print(
            "Wheel smoke passed: uvx initialization, repeatability, diagnostics, and five packaged skills."
        )


if __name__ == "__main__":
    main()
