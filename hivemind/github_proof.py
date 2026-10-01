"""Hivemind evidence policy, independent of the GitHub API client library."""

import re
from typing import TYPE_CHECKING, Any

from .models import CheckPolicy

if TYPE_CHECKING:
    from .github import GitHub


def verify(
    api: "GitHub",
    repo: str,
    commit: str,
    pr_number: int,
    required_checks: list[CheckPolicy],
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit) or pr_number < 1:
        raise ValueError("Proof requires a full commit SHA and positive PR number")
    commit = commit.lower()
    path = f"/repos/{repo}/pulls/{pr_number}"
    pr = api.get(path)
    if (
        pr["base"]["repo"]["full_name"].lower() != repo.lower()
        or pr["head"]["sha"] != commit
    ):
        raise ValueError("PR repository or current head does not match submitted proof")
    if pr["state"] == "closed" and not pr.get("merged"):
        raise ValueError("PR was closed without merging")
    runs = api.pages(
        f"/repos/{repo}/commits/{commit}/check-runs?filter=latest", "check_runs"
    )
    statuses = api.get(f"/repos/{repo}/commits/{commit}/status")
    if not runs or any(
        c["status"] != "completed" or c.get("conclusion") != "success" for c in runs
    ):
        raise ValueError("Every reported GitHub check must complete successfully")
    if statuses.get("total_count", 0) and statuses["state"] != "success":
        raise ValueError("GitHub commit statuses have not all passed")
    for policy in required_checks:
        if not any(
            c["name"] == policy.name and c["app"]["id"] == policy.app_id for c in runs
        ):
            raise ValueError(
                f"Missing successful trusted check: {policy.name} (app {policy.app_id})"
            )
    latest = api.get(path)
    if latest["head"]["sha"] != commit or (
        latest["state"] == "closed" and not latest.get("merged")
    ):
        raise ValueError("PR changed during verification; submit its current head")
    return {
        "commit": commit,
        "pr": pr_number,
        "url": pr["html_url"],
        "checks": [
            {
                "id": c["id"],
                "name": c["name"],
                "app_id": c["app"]["id"],
                "result": c["conclusion"],
                "url": c.get("html_url"),
            }
            for c in runs
        ],
    }
