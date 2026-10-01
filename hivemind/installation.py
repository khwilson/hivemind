"""Repeatable installation of the standalone CLI's repository assets."""

import hashlib
import json
import re
import subprocess
from importlib.resources import files
from pathlib import Path
from typing import Any

from .configuration import CONFIG, parse_settings, serialize_settings
from .github_client import ApiError, GitHub, validate_repo
from .models import CheckPolicy, ProjectConfig, Rule, Settings, StandardWork

SOURCE = "git+https://github.com/khwilson/hivemind.git@v0.1.2"
START, END = "<!-- hivemind:start -->", "<!-- hivemind:end -->"


def dump(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def project_slug(repo: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "-", repo.split("/")[1].lower())[:64]


def checked_path(root: Path, relative: str) -> Path:
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError(f"Managed path must remain inside checkout: {relative}")
    return path


def read_settings(root: Path) -> Settings:
    return parse_settings(checked_path(root.resolve(), CONFIG).read_text())


def checkout_repo(root: Path) -> str | None:
    if not (root / ".git").exists():
        return None
    result = subprocess.run(
        ["git", "-C", str(root), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        return None
    remote = (
        result.stdout.strip()
        .removeprefix("git@github.com:")
        .removeprefix("ssh://git@github.com/")
    )
    return validate_repo(remote).lower()


def merge_agents(original: str, block: str) -> str:
    if original.count(START) != original.count(END) or original.count(START) > 1:
        raise ValueError("Repair malformed Hivemind markers in AGENTS.md first")
    if START in original:
        start, end = original.index(START), original.index(END) + len(END)
        if original.index(END) < start:
            raise ValueError("Repair reversed Hivemind markers in AGENTS.md first")
        return original[:start] + block.rstrip() + original[end:]
    return original.rstrip() + ("\n\n" if original.strip() else "") + block


def initialize(
    root: Path,
    repo: str,
    maintainers: list[int],
    checks: list[CheckPolicy],
    profile: str | None = None,
    branch: str | None = None,
    source: str | None = None,
    project: str | None = None,
    dry_run: bool = False,
    code_owner: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    repo = validate_repo(repo).lower()
    existing_manifest = checked_path(root, ".hivemind/templates.json")
    installed = (
        json.loads(existing_manifest.read_text()) if existing_manifest.exists() else {}
    )
    profile = profile or installed.get("profile", "general")
    branch = branch or installed.get("default_branch", "main")
    source = source or installed.get("package_source", SOURCE)
    if profile not in {"general", "mathematics"}:
        raise ValueError("Profile must be general or mathematics")
    if not re.fullmatch(r"[A-Za-z0-9_/.-]+", branch) or branch.startswith("-"):
        raise ValueError("Use a normal default-branch name")
    if not re.fullmatch(
        r"git\+https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git@[A-Za-z0-9_.-]+",
        source,
    ):
        raise ValueError("Package source must be a pinned GitHub git+https URL")
    origin = checkout_repo(root)
    if origin is not None and origin != repo:
        raise ValueError("Checkout origin differs from the requested repository")
    config_path = checked_path(root, CONFIG)
    legacy = checked_path(root, ".hivemind/config.json")
    if not config_path.exists() and legacy.exists():
        settings = Settings.model_validate_json(legacy.read_text())
        standard = checked_path(root, ".hivemind/standard-work.json")
        if standard.exists():
            settings.standard_work = StandardWork.model_validate_json(
                standard.read_text()
            )
    else:
        settings = None
    if config_path.exists() or settings is not None:
        settings = read_settings(root) if config_path.exists() else settings
        assert settings is not None
        if (
            settings.hub != repo
            or len(settings.projects) != 1
            or settings.projects[0].repo.lower() != repo
        ):
            raise ValueError("Existing configuration must govern this repository only")
        if project is not None and settings.projects[0].id != project:
            raise ValueError("Existing project ID cannot be changed by initialization")
    else:
        if not maintainers or not checks:
            raise ValueError(
                "First initialization requires --maintainer-id and --required-check NAME:APP_ID"
            )
        settings = Settings(
            hub=repo,
            maintainers=maintainers,
            standard_work=StandardWork(
                rules=[
                    Rule(
                        id="mathematics-generalization",
                        version=1,
                        enabled=profile == "mathematics",
                        paths=["**/*.lean", "*.lean", "**/*.tex", "*.tex"],
                        skill="mathematics-generalization",
                    )
                ]
            ),
            projects=[
                ProjectConfig(
                    id=project or project_slug(repo),
                    name=repo.split("/")[1],
                    repo=repo,
                    required_checks=checks,
                )
            ],
        )
    if code_owner is not None and not re.fullmatch(
        r"[A-Za-z0-9-]+(?:/[A-Za-z0-9-]+)?", code_owner
    ):
        raise ValueError("Code owner must be a GitHub username or organization/team")
    project_id = settings.projects[0].id
    resource = files("hivemind").joinpath("templates")
    replacements = {
        "@@REPO@@": repo,
        "@@PROJECT@@": project_id,
        "@@SOURCE@@": source,
        "@@BRANCH_JSON@@": json.dumps(branch),
    }

    def render(name: str) -> str:
        text = resource.joinpath(name).read_text()
        for key, value in replacements.items():
            text = text.replace(key, value)
        return text

    proposed: dict[str, str] = {
        ".github/workflows/hivemind-broker.yml": render("broker.yml"),
    }
    if code_owner is not None:
        proposed[".github/CODEOWNERS"] = (
            "# Hivemind trusted coordinator owners\n"
            + "".join(
                f"{path} @{code_owner}\n"
                for path in [
                    "/.github/",
                    "/hivemind.toml",
                    "/.hivemind/skills/",
                    "/pyproject.toml",
                    "/uv.lock",
                    "/hivemind/",
                ]
            )
        )
    elif checked_path(root, ".github/CODEOWNERS").exists():
        owners = checked_path(root, ".github/CODEOWNERS").read_text()
        migrated = re.sub(
            r"^/\.hivemind/config\.json(.*)$",
            r"/hivemind.toml\1",
            owners,
            flags=re.MULTILINE,
        )
        migrated = re.sub(
            r"^/\.hivemind/(?:project|standard-work)\.json.*\n?",
            "",
            migrated,
            flags=re.MULTILINE,
        )
        if migrated != owners:
            proposed[".github/CODEOWNERS"] = migrated
    for skill in resource.joinpath("skills").iterdir():
        if skill.is_dir():
            proposed[f".hivemind/skills/{skill.name}/SKILL.md"] = skill.joinpath(
                "SKILL.md"
            ).read_text()
    if not config_path.exists():
        proposed[CONFIG] = serialize_settings(settings)
    manifest_path = checked_path(root, ".hivemind/templates.json")
    previous = (
        json.loads(manifest_path.read_text()).get("files", {})
        if manifest_path.exists()
        else {}
    )
    changed: list[str] = []
    preserved: list[str] = []
    conflicts: list[str] = []
    hashes = {
        k: v
        for k, v in previous.items()
        if k
        not in {
            ".hivemind/config.json",
            ".hivemind/project.json",
            ".hivemind/standard-work.json",
        }
    }
    writes: dict[str, str] = {}
    for relative, content in proposed.items():
        path = checked_path(root, relative)
        current = path.read_text() if path.exists() else None
        if current == content:
            preserved.append(relative)
        elif current is not None and hashlib.sha256(
            current.encode()
        ).hexdigest() != previous.get(relative):
            conflicts.append(relative)
            continue
        else:
            writes[relative] = content
            changed.append(relative)
        hashes[relative] = hashlib.sha256(content.encode()).hexdigest()
    agents_path = checked_path(root, "AGENTS.md")
    original = agents_path.read_text() if agents_path.exists() else ""
    block = render("AGENTS.md")
    old_block = (
        original[original.index(START) : original.index(END) + len(END)]
        if START in original and END in original
        else None
    )
    if (
        old_block is not None
        and old_block != block.rstrip()
        and hashlib.sha256(old_block.encode()).hexdigest()
        != previous.get("AGENTS.md#hivemind")
    ):
        conflicts.append("AGENTS.md#hivemind")
        merge_agents(original, block)  # Validate markers even when preserving edits.
    else:
        updated = merge_agents(original, block)
        if updated != original:
            writes["AGENTS.md"] = updated
            changed.append("AGENTS.md")
        hashes["AGENTS.md#hivemind"] = hashlib.sha256(
            block.rstrip().encode()
        ).hexdigest()
    manifest = dump(
        {
            "version": 1,
            "package_source": source,
            "profile": profile,
            "default_branch": branch,
            "files": hashes,
        }
    )
    if not manifest_path.exists() or manifest_path.read_text() != manifest:
        writes[".hivemind/templates.json"] = manifest
        changed.append(".hivemind/templates.json")
    # Resolve every managed path before performing any writes.
    for relative in [*writes, ".hivemind/hints", ".hivemind/reviews"]:
        checked_path(root, relative)
    if not dry_run:
        for relative, content in writes.items():
            path = checked_path(root, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        checked_path(root, ".hivemind/hints").mkdir(parents=True, exist_ok=True)
        checked_path(root, ".hivemind/reviews").mkdir(parents=True, exist_ok=True)
    return {
        "repo": repo,
        "project": project_id,
        "changed": changed,
        "preserved": preserved,
        "conflicts": conflicts,
        "dry_run": dry_run,
        "next": "Review and commit the installation, then run hivemind setup.",
    }


def setup_plan(repo: str, branch: str, app_id: int) -> dict[str, Any]:
    if app_id <= 0:
        raise ValueError("Broker App ID must be positive")
    repo = validate_repo(repo)

    def ruleset(
        name: str, ref: str, rules: list[dict[str, Any]], bypass: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {
            "name": name,
            "target": "branch",
            "enforcement": "active",
            "conditions": {
                "ref_name": {"include": [f"refs/heads/{ref}"], "exclude": []}
            },
            "rules": rules,
            "bypass_actors": bypass,
        }

    return {
        "repo": repo,
        "environment": {
            "name": "coordination",
            "deployment_branch_policy": {
                "protected_branches": False,
                "custom_branch_policies": True,
            },
        },
        "branch_policy": {"name": branch, "type": "branch"},
        "rulesets": [
            ruleset(
                "Hivemind state access",
                "hivemind-state",
                [
                    {"type": "creation"},
                    {
                        "type": "update",
                        "parameters": {"update_allows_fetch_and_merge": False},
                    },
                ],
                [
                    {
                        "actor_type": "Integration",
                        "actor_id": app_id,
                        "bypass_mode": "always",
                    }
                ],
            ),
            ruleset(
                "Hivemind state history",
                "hivemind-state",
                [{"type": "deletion"}, {"type": "non_fast_forward"}],
                [],
            ),
            ruleset(
                "Hivemind coordinator review",
                branch,
                [
                    {
                        "type": "pull_request",
                        "parameters": {
                            "required_approving_review_count": 1,
                            "dismiss_stale_reviews_on_push": True,
                            "require_code_owner_review": True,
                            "require_last_push_approval": True,
                            "required_review_thread_resolution": True,
                        },
                    },
                    {"type": "deletion"},
                    {"type": "non_fast_forward"},
                ],
                [],
            ),
        ],
        "manual_steps": [
            "Install the broker App in this repository with contents/Issues write and checks/PRs read.",
            "Set coordination environment variable HIVEMIND_APP_CLIENT_ID and secret HIVEMIND_APP_PRIVATE_KEY.",
            "Require trusted CODEOWNERS for coordination code, workflows, policy, dependencies, and CODEOWNERS itself.",
            "Agent credentials must not have administration access or trusted-owner identity.",
        ],
    }


def apply_setup(root: Path, api: GitHub, app_id: int, client_id: str) -> dict[str, Any]:
    from .broker import Hub
    from .models import State

    settings = read_settings(root)
    repo = settings.hub
    metadata = api.get(f"/repos/{repo}")
    if not metadata.get("permissions", {}).get("admin"):
        raise ValueError("Setup needs repository administration access")
    branch = metadata["default_branch"]
    remote = parse_settings(api.text_file(repo, CONFIG, branch))
    if remote != settings:
        raise ValueError(
            "Commit the reviewed installation to the default branch before setup"
        )
    plan = setup_plan(repo, branch, app_id)
    # Check existing policies before mutating state or repository settings.
    existing = api.pages(f"/repos/{repo}/rulesets?includes_parents=false")
    missing = []
    for desired in plan["rulesets"]:
        prior = next((r for r in existing if r["name"] == desired["name"]), None)
        if prior:
            actual = api.get(f"/repos/{repo}/rulesets/{prior['id']}")
            if any(actual.get(k) != v for k, v in desired.items()):
                raise ValueError(
                    f"Existing ruleset differs: {desired['name']}; reconcile it before setup"
                )
        else:
            missing.append(desired)
    env = f"/repos/{repo}/environments/coordination"
    try:
        api.get(env)
        policies = api.pages(env + "/deployment-branch-policies", "branch_policies")
    except ApiError as exc:
        if exc.status != 404:
            raise
        policies = []
    if any(
        p["name"] != branch or p.get("type", "branch") != "branch" for p in policies
    ):
        raise ValueError(
            "Coordination environment has other branch/tag policies; remove them explicitly"
        )
    workflow_path = ".github/workflows/hivemind-broker.yml"
    if (
        api.text_file(repo, workflow_path, branch)
        != checked_path(root.resolve(), workflow_path).read_text()
    ):
        raise ValueError("Reviewed broker workflow differs from local installation")
    api.text_file(
        repo, ".github/CODEOWNERS", branch
    )  # Must be installed before protecting main.
    hub = Hub(settings, api)
    parent, _ = hub.load()
    if parent is None:
        hub.publish(
            None,
            State(standard_cursor=api.get(f"/repos/{repo}/commits/{branch}")["sha"]),
            "Initialize Hivemind state",
        )
    for desired in missing:
        api.request(f"/repos/{repo}/rulesets", "POST", desired)
    api.request(
        env,
        "PUT",
        {"deployment_branch_policy": plan["environment"]["deployment_branch_policy"]},
    )
    if not policies:
        api.request(env + "/deployment-branch-policies", "POST", plan["branch_policy"])
    repo_id = metadata["id"]
    variable_path = f"/repositories/{repo_id}/environments/coordination/variables"
    current = api.pages(variable_path, "variables")
    variable = {"name": "HIVEMIND_APP_CLIENT_ID", "value": client_id}
    if any(v["name"] == variable["name"] for v in current):
        api.request(variable_path + "/HIVEMIND_APP_CLIENT_ID", "PATCH", variable)
    else:
        api.request(variable_path, "POST", variable)
    return {
        "status": "settings-applied",
        "repo": repo,
        "remaining": plan["manual_steps"],
        "next": "Install the App credential, ensure trusted CODEOWNERS, then run doctor. Setup is not yet verified.",
    }
