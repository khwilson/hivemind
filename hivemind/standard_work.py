"""Deterministic generation of mathematical review tasks from integrated changes."""

import fnmatch
import hashlib

from .github import GitHub
from .models import Rule as Rule
from .models import Settings, StandardWork, State
from .queue import Queue


def reconcile(
    state: State,
    settings: Settings,
    config: StandardWork,
    api: GitHub,
    config_sha: str,
    now: int,
) -> int:
    if len(settings.projects) != 1 or settings.projects[0].repo.lower() != settings.hub:
        raise ValueError("Standard work requires a repository-local project")
    metadata = api.get(f"/repos/{settings.hub}")
    head = api.get(f"/repos/{settings.hub}/commits/{metadata['default_branch']}")["sha"]
    if state.standard_cursor is None:
        state.standard_cursor = (
            head  # Installation baseline, no implicit historical backfill.
        )
        return 0
    if state.standard_cursor == head:
        return 0
    base = state.standard_cursor
    comparison = api.get(f"/repos/{settings.hub}/compare/{base}...{head}")
    if comparison["status"] not in ("ahead", "identical"):
        raise ValueError(
            "Default-branch history diverged; explicitly reconcile the standard-work cursor"
        )
    changed = comparison.get("files", [])
    if len(changed) >= 300:
        raise ValueError(
            "Diff reached GitHub file limit; split/reconcile this batch before advancing the cursor"
        )
    paths = [
        f["filename"]
        for f in changed
        if not f["filename"].startswith((".hivemind/", ".github/"))
    ]
    queue = Queue(state, settings)
    count = 0
    for rule in config.rules:
        if not rule.enabled or not any(
            fnmatch.fnmatchcase(path, pattern)
            for path in paths
            for pattern in rule.paths
        ):
            continue
        identity = f"{settings.hub}:{rule.id}:{rule.version}:{base}:{head}"
        generation = hashlib.sha256(identity.encode()).hexdigest()
        if generation in state.generation_ids:
            continue
        result = queue.apply(
            settings.projects[0].id,
            "add",
            {
                "title": f"Inspect mathematical changes for {rule.skill.removeprefix('mathematics-')}",
                "criteria": f"Inspect changes {base}..{head}. Commit .hivemind/reviews/TASK.md with source SHA, theorem references, assumptions, findings, validation, and follow-ups. Distinguish proved extensions, conjectures, and counterexamples. A justified finding of no useful extension is valid.",
                "priority": rule.priority,
            },
            "broker",
            generation[:32],
            now,
        )
        task = queue.task(queue.project(settings.projects[0].id), result["id"])
        task.provenance = {
            "kind": "standard-work",
            "rule": rule.id,
            "rule_version": rule.version,
            "repo": settings.hub,
            "base": base,
            "commit": head,
            "config_sha": config_sha,
            "skill": rule.skill,
            "generation_id": generation,
        }
        state.generation_ids.append(generation)
        count += 1
    state.standard_cursor = head
    return count
