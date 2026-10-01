"""Inspect installed files and live GitHub protection settings."""

import json
from pathlib import Path
from typing import Any

from .configuration import CONFIG, parse_settings
from .github import GitHub
from .installation import checked_path, read_settings, setup_plan


def doctor(
    root: Path, api: GitHub | None = None, app_id: int | None = None
) -> dict[str, Any]:
    root = root.resolve()
    settings = read_settings(root)
    findings: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        findings.append({"check": name, "ok": ok, "detail": detail})

    check(
        "repository-local registry",
        len(settings.projects) == 1
        and settings.projects[0].repo.lower() == settings.hub,
    )
    check("trusted maintainers", bool(settings.maintainers))
    standard = settings.standard_work
    check(
        "standard-work rules",
        len({r.id for r in standard.rules}) == len(standard.rules),
    )
    manifest = json.loads(checked_path(root, ".hivemind/templates.json").read_text())
    for path in manifest["files"]:
        check(f"installed {path}", checked_path(root, path.split("#")[0]).is_file())
    if api is None:
        return {
            "status": "local-valid" if all(f["ok"] for f in findings) else "incomplete",
            "repo": settings.hub,
            "checks": findings,
            "live_verified": False,
        }
    repo = settings.hub
    metadata = api.get(f"/repos/{repo}")
    branch = metadata["default_branch"]
    remote_config = parse_settings(api.text_file(repo, CONFIG, branch))
    check("reviewed default-branch config", remote_config == settings)
    expected = setup_plan(repo, branch, app_id or 1)
    rulesets = api.pages(f"/repos/{repo}/rulesets?includes_parents=true")
    for desired in expected["rulesets"]:
        matches = [r for r in rulesets if r["name"] == desired["name"]]
        ok = False
        if len(matches) == 1:
            actual = api.get(f"/repos/{repo}/rulesets/{matches[0]['id']}")
            ok = all(actual.get(k) == v for k, v in desired.items())
        check(
            desired["name"],
            ok and app_id is not None,
            "Supply the broker --app-id and reconcile differing rulesets",
        )
    env = f"/repos/{repo}/environments/coordination"
    environment = api.get(env)
    check(
        "restricted environment",
        environment.get("deployment_branch_policy")
        == expected["environment"]["deployment_branch_policy"],
    )
    policies = api.pages(env + "/deployment-branch-policies", "branch_policies")
    check(
        "only default branch allowed",
        len(policies) == 1
        and policies[0]["name"] == branch
        and policies[0].get("type") == "branch",
    )
    check(
        "App environment secret present",
        any(
            s["name"] == "HIVEMIND_APP_PRIVATE_KEY"
            for s in api.pages(
                f"/repositories/{metadata['id']}/environments/coordination/secrets",
                "secrets",
            )
        ),
    )
    variables = api.get(
        f"/repositories/{metadata['id']}/environments/coordination/variables"
    )["variables"]
    check(
        "App client ID present",
        any(v["name"] == "HIVEMIND_APP_CLIENT_ID" and v["value"] for v in variables),
    )
    owners = api.text_file(repo, ".github/CODEOWNERS", branch)
    check(
        "CODEOWNERS present",
        bool(owners.strip()),
        "Review owner identities and coverage; presence alone does not prove correct ownership",
    )
    try:
        api.json_file(repo, "index.json", settings.state_branch)
        check("state branch initialized", True)
    except ValueError:
        check("state branch initialized", False)
    # Configuration inspection cannot prove private-key custody or behavior of arbitrary workflows.
    return {
        "status": "settings-valid" if all(f["ok"] for f in findings) else "incomplete",
        "repo": repo,
        "checks": findings,
        "live_verified": True,
        "remaining": "Inspect CODEOWNERS coverage and run agent negative-access smoke tests before declaring deployment ready.",
    }
