"""One offline verification command after uv sync --locked."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(*arguments: str) -> None:
    subprocess.run([sys.executable, "-m", *arguments], cwd=ROOT, check=True)


def main() -> None:
    run("ruff", "check", ".")
    run("ruff", "format", "--check", ".")
    run("ty", "check", "--python", sys.executable)
    run("pytest")
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)
        run("generate", "--output", str(output))
        for name in (
            "models.py",
            "client.py",
            "raw_models.py",
            "raw_api.py",
            "raw_api.pyi",
        ):
            if (output / name).read_bytes() != (ROOT / "generated" / name).read_bytes():
                raise RuntimeError(f"Generated output differs: {name}")
    print("Checks and offline regeneration passed.")


if __name__ == "__main__":
    main()
