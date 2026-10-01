from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ty_checks_literals_response_fields_and_awaiting(tmp_path: Path) -> None:
    sample = tmp_path / "consumer.py"
    imports = """from generated.raw_api import SyncGhApi, AsyncGhApi
from generated.models import ChecksListForRefQuery
"""
    valid = (
        imports
        + """
def sync(api: SyncGhApi) -> str:
    result = api.git.get_ref(ref="heads/main")
    api.checks.list_for_ref(ref="main", filter="all", status="completed")
    query = ChecksListForRefQuery(filter="all")
    return result["object"]["sha"]

async def asynchronous(api: AsyncGhApi) -> str:
    result = await api.git.get_ref(ref="heads/main")
    return result["object"]["sha"]
"""
    )
    command = [
        sys.executable,
        "-m",
        "ty",
        "check",
        "--python",
        sys.executable,
        "--extra-search-path",
        str(ROOT),
        str(sample),
    ]
    sample.write_text(valid)
    accepted = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    sample.write_text(
        imports
        + """
def invalid(api: SyncGhApi) -> int:
    api.checks.list_for_ref(filter="bogus")
    query = ChecksListForRefQuery(filter="bogus")
    result = api.git.get_ref(ref="heads/main")
    return result["object"]["sha"]
"""
    )
    rejected = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert rejected.returncode != 0
    assert rejected.stdout.count("error[invalid-argument-type]") == 2
    assert "error[invalid-return-type]" in rejected.stdout
