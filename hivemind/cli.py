"""Standalone Typer interface for repository setup and signed queue requests."""

import base64
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Callable

import typer

from .broker import execute_broker
from .client import Client
from .configuration import CONFIG, write_agents
from .doctor import doctor as inspect_installation
from .github_client import ApiError, GitHub, validate_repo
from .installation import (
    SOURCE,
    apply_setup,
    checked_path,
    dump,
    initialize,
    read_settings,
    setup_plan,
)
from .models import Action, Agent, CheckPolicy, Settings
from .signing import generate, key_id

app = typer.Typer(
    help="Standalone GitHub work queues and repository setup.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
tasks = typer.Typer(
    help="Create and edit broker-validated queue tasks.", no_args_is_help=True
)
agents = typer.Typer(
    help="Prepare reviewed changes to the agent allowlist.", no_args_is_help=True
)
broker = typer.Typer(
    help="Trusted workflow broker; not an agent runner.", no_args_is_help=True
)
app.add_typer(tasks, name="task")
app.add_typer(agents, name="agent")
app.add_typer(broker, name="broker")
requests = typer.Typer(help="Inspect durable request receipts.", no_args_is_help=True)
app.add_typer(requests, name="request")


@dataclass
class Options:
    repo: str | None
    project: str | None
    key: Path | None
    wait: int
    path: Path


def perform(operation: Callable[[], Any]) -> Any:
    try:
        result = operation()
        typer.echo(dump(result))
        return result
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.callback()
def configure(
    ctx: typer.Context,
    repo: Annotated[str | None, typer.Option(envvar="HIVEMIND_REPO")] = None,
    project: Annotated[str | None, typer.Option(envvar="HIVEMIND_PROJECT")] = None,
    key: Annotated[Path | None, typer.Option(envvar="HIVEMIND_KEY")] = None,
    wait: Annotated[
        int,
        typer.Option(
            min=0,
            max=600,
            help="Wait for a receipt; default returns pending immediately.",
        ),
    ] = 0,
    path: Annotated[
        Path, typer.Option(help="Repository checkout or installation directory.")
    ] = Path("."),
) -> None:
    ctx.obj = Options(repo, project, key, wait, path.resolve())


def context(ctx: typer.Context) -> Options:
    obj = ctx.obj
    if not isinstance(obj, Options):
        raise ValueError("CLI context is missing")
    return obj


def connection(ctx: typer.Context) -> tuple[Client, str]:
    opts = context(ctx)
    repo, project = opts.repo, opts.project
    if (opts.path / CONFIG).exists():
        settings = read_settings(opts.path)
        repo = repo or settings.hub
        if repo.lower() == settings.hub:
            project = project or settings.projects[0].id
    if not repo:
        raise ValueError("Pass --repo OWNER/REPO or run inside an initialized checkout")
    if not project:
        from .installation import project_slug

        project = project_slug(validate_repo(repo))
    return Client(repo, opts.key, opts.wait), project


def send(ctx: typer.Context, action: Action, args: dict[str, Any]) -> None:
    def operation() -> dict[str, Any]:
        client, project = connection(ctx)
        return client.send(project, action, args)

    perform(operation)


@app.command()
def init(
    ctx: typer.Context,
    repo: Annotated[str, typer.Option(help="Target owner/name.")],
    maintainer_id: Annotated[list[int] | None, typer.Option(min=1)] = None,
    required_check: Annotated[
        list[str] | None, typer.Option(help="Repeat NAME:TRUSTED_APP_ID.")
    ] = None,
    profile: Annotated[
        str | None,
        typer.Option(help="general or mathematics; preserve an existing profile."),
    ] = None,
    default_branch: Annotated[str | None, typer.Option()] = None,
    source: Annotated[
        str | None,
        typer.Option(help="Pinned CLI source; preserve an existing selection."),
    ] = None,
    dry_run: Annotated[bool, typer.Option()] = False,
    code_owner: Annotated[
        str | None, typer.Option(help="Trusted GitHub username or organization/team.")
    ] = None,
) -> None:
    """Prepare versioned instructions, skills, policy, and broker without GitHub writes."""

    def operation() -> dict[str, Any]:
        checks = []
        for value in required_check or []:
            name, _, issuer = value.rpartition(":")
            if not name or not issuer.isdecimal():
                raise ValueError("Required checks use NAME:APP_ID")
            checks.append(CheckPolicy(name=name, app_id=int(issuer)))
        opts = context(ctx)
        return initialize(
            opts.path,
            repo,
            maintainer_id or [],
            checks,
            profile,
            default_branch,
            source,
            opts.project,
            dry_run,
            code_owner,
        )

    result = perform(operation)
    if result["conflicts"]:
        raise typer.Exit(1)


@app.command()
def upgrade(
    ctx: typer.Context,
    source: Annotated[str, typer.Option()] = SOURCE,
    dry_run: Annotated[bool, typer.Option()] = False,
) -> None:
    """Update bundled assets while preserving human edits and reporting conflicts."""

    def operation() -> dict[str, Any]:
        opts = context(ctx)
        settings = (
            read_settings(opts.path)
            if (opts.path / CONFIG).exists()
            else Settings.model_validate_json(
                checked_path(opts.path.resolve(), ".hivemind/config.json").read_text()
            )
        )
        manifest = json.loads(
            checked_path(opts.path, ".hivemind/templates.json").read_text()
        )
        return initialize(
            opts.path,
            settings.hub,
            settings.maintainers,
            settings.projects[0].required_checks,
            manifest["profile"],
            manifest["default_branch"],
            source,
            dry_run=dry_run,
        )

    result = perform(operation)
    if result["conflicts"]:
        raise typer.Exit(1)


@app.command()
def setup(
    ctx: typer.Context,
    app_id: Annotated[int, typer.Option(min=1)],
    client_id: Annotated[str | None, typer.Option()] = None,
    apply: Annotated[
        bool,
        typer.Option(help="Apply settings with your administrator GitHub credentials."),
    ] = False,
) -> None:
    """Show a concrete GitHub setup plan; --apply initializes state and applies settings."""

    def operation() -> dict[str, Any]:
        root = context(ctx).path
        settings = read_settings(root)
        manifest = json.loads(
            checked_path(root, ".hivemind/templates.json").read_text()
        )
        if apply:
            if not client_id:
                raise ValueError("--client-id is required with --apply")
            return apply_setup(root, GitHub(), app_id, client_id)
        return setup_plan(settings.hub, manifest["default_branch"], app_id)

    perform(operation)


@app.command(name="doctor")
def doctor_command(
    ctx: typer.Context,
    local: Annotated[
        bool, typer.Option(help="Check local installation without GitHub access.")
    ] = False,
    app_id: Annotated[int | None, typer.Option(min=1)] = None,
) -> None:
    """Check files and live GitHub protections; reports incomplete deployment honestly."""
    result = perform(
        lambda: inspect_installation(
            context(ctx).path, None if local else GitHub(), app_id
        )
    )
    if result["status"] == "incomplete":
        raise typer.Exit(1)


@app.command()
def keygen(
    out: Annotated[
        Path, typer.Option(help="New private key path outside repositories.")
    ],
) -> None:
    """Generate an Ed25519 private key (0600) and public registration fields."""
    perform(lambda: generate(out.expanduser()))


@app.command()
def whoami() -> None:
    """Show the GitHub account and stable ID used for agent registration."""
    perform(
        lambda: {k: v for k, v in GitHub().get("/user").items() if k in ("id", "login")}
    )


@agents.command("register")
def register(
    ctx: typer.Context,
    name: Annotated[str, typer.Option()],
    github_id: Annotated[int, typer.Option(min=1)],
    public_key: Annotated[str, typer.Option()],
) -> None:
    """Add public agent identity locally; review and commit the registry change."""

    def operation() -> dict[str, Any]:
        root = context(ctx).path
        settings = read_settings(root)
        raw = base64.b64decode(public_key, validate=True)
        if len(raw) != 32:
            raise ValueError("Public key must be a base64 Ed25519 key (32 bytes)")
        identity = key_id(raw)
        if any(a.id == identity for a in settings.agents):
            raise ValueError(
                "Key already registered; edit its reviewed configuration explicitly"
            )
        agent = Agent(
            id=identity,
            name=name,
            github_id=github_id,
            public_key=public_key,
            projects=[settings.projects[0].id],
        )
        settings.agents.append(agent)
        write_agents(checked_path(root.resolve(), CONFIG), settings)
        return {
            "agent": agent.model_dump(),
            "next": "Review and commit the protected registry change; registration is not effective yet.",
        }

    perform(operation)


@agents.command("revoke")
def revoke(ctx: typer.Context, agent: str) -> None:
    """Prepare a reviewed key revocation; broker reconciliation expires its claims."""

    def operation() -> dict[str, Any]:
        root = context(ctx).path
        settings = read_settings(root)
        registered = next((a for a in settings.agents if a.id == agent), None)
        if registered is None:
            raise ValueError("Agent key not registered")
        registered.revoked = True
        write_agents(checked_path(root.resolve(), CONFIG), settings)
        return {
            "agent": agent,
            "next": "Review and commit revocation to the protected default branch.",
        }

    perform(operation)


@app.command()
def kick(ctx: typer.Context) -> None:
    """Request a broker run on the repository's current default branch."""

    def operation() -> dict[str, Any]:
        client, _ = connection(ctx)
        api, repo = client.api, client.hub
        metadata = api.get(f"/repos/{repo}")
        workflow_path = f"/repos/{repo}/actions/workflows/hivemind-broker.yml"
        workflow = api.get(workflow_path)
        if workflow["state"] != "active":
            raise ValueError("Broker workflow is disabled; enable it in GitHub Actions")
        try:
            result = api.request(
                workflow_path + "/dispatches",
                "POST",
                {"ref": metadata["default_branch"]},
            )
        except ApiError as exc:
            if exc.status == 403:
                raise ValueError(
                    f"{exc}; kick requires Actions write permission on the target "
                    "repository (or a compatible classic token with repo scope)"
                ) from exc
            raise
        return {
            "status": "dispatched",
            "repo": repo,
            "ref": metadata["default_branch"],
            "url": (result or {}).get("html_url")
            or f"https://github.com/{repo}/actions/workflows/hivemind-broker.yml",
        }

    perform(operation)


@app.command()
def status(ctx: typer.Context) -> None:
    """Read the repository's materialized task snapshot."""
    perform(lambda: connection(ctx)[0].state())


@requests.command("show")
def request_show(ctx: typer.Context, request_id: str) -> None:
    """Read a receipt after a pending claim or edit; no work starts without acceptance."""
    result = perform(lambda: connection(ctx)[0].receipt(request_id))
    if result["status"] == "rejected":
        raise typer.Exit(1)


@tasks.command("show")
def show(ctx: typer.Context, task: str) -> None:
    def operation() -> dict[str, Any]:
        client, project = connection(ctx)
        for item in client.state()["projects"]:
            if item["id"] == project:
                for entry in item["tasks"]:
                    if entry["id"] == task:
                        return entry
        raise ValueError("Task not found in this project")

    perform(operation)


@tasks.command("add")
def add(
    ctx: typer.Context,
    title: Annotated[str, typer.Option()],
    criteria: Annotated[str, typer.Option()],
    parent: Annotated[str | None, typer.Option()] = None,
    depends_on: Annotated[list[str] | None, typer.Option()] = None,
    priority: Annotated[int, typer.Option(min=1, max=3)] = 2,
) -> None:
    """Add a task or subtask through the broker's durable inbox."""
    send(
        ctx,
        "add",
        {
            "title": title,
            "criteria": criteria,
            "parent": parent,
            "dependencies": depends_on or [],
            "priority": priority,
        },
    )


@tasks.command("edit")
def edit(
    ctx: typer.Context,
    task: str,
    revision: Annotated[int, typer.Option(min=1)],
    title: Annotated[str | None, typer.Option()] = None,
    criteria: Annotated[str | None, typer.Option()] = None,
    parent: Annotated[str | None, typer.Option()] = None,
    clear_parent: Annotated[bool, typer.Option()] = False,
    depends_on: Annotated[list[str] | None, typer.Option()] = None,
    clear_dependencies: Annotated[bool, typer.Option()] = False,
    priority: Annotated[int | None, typer.Option(min=1, max=3)] = None,
    release_claim: Annotated[bool, typer.Option()] = False,
) -> None:
    """Edit an expected task revision; material changes invalidate active claims."""
    args: dict[str, Any] = {
        "task": task,
        "expected_revision": revision,
        "release_claim": release_claim,
    }
    for field, value in [
        ("title", title),
        ("criteria", criteria),
        ("priority", priority),
    ]:
        if value is not None:
            args[field] = value
    if parent is not None or clear_parent:
        args["parent"] = None if clear_parent else parent
    if depends_on is not None or clear_dependencies:
        args["dependencies"] = [] if clear_dependencies else depends_on
    send(ctx, "edit", args)


@tasks.command("cancel")
def cancel(
    ctx: typer.Context, task: str, revision: Annotated[int, typer.Option(min=1)]
) -> None:
    """Cancel an expected revision without deleting audit history."""
    send(ctx, "cancel", {"task": task, "expected_revision": revision})


@tasks.command("prioritize")
def prioritize(
    ctx: typer.Context,
    ordered_tasks: Annotated[list[str], typer.Argument()],
    revision: Annotated[int, typer.Option(min=1, help="Queue revision from status.")],
) -> None:
    """Set complete ordering, preserving active claims and rejecting stale requests."""
    send(ctx, "prioritize", {"tasks": ordered_tasks, "expected_revision": revision})


@tasks.command("note")
def note(ctx: typer.Context, task: str, text: Annotated[str, typer.Option()]) -> None:
    send(ctx, "note", {"task": task, "text": text})


@app.command()
def claim(
    ctx: typer.Context, task: Annotated[str | None, typer.Option()] = None
) -> None:
    """Ownership begins only after an accepted broker receipt."""
    send(ctx, "claim", {"task": task})


@app.command()
def heartbeat(
    ctx: typer.Context, task: str, claim_id: Annotated[str, typer.Option()]
) -> None:
    send(ctx, "heartbeat", {"task": task, "claim_id": claim_id})


@app.command()
def release(
    ctx: typer.Context, task: str, claim_id: Annotated[str, typer.Option()]
) -> None:
    send(ctx, "release", {"task": task, "claim_id": claim_id})


@app.command()
def submit(
    ctx: typer.Context,
    task: str,
    claim_id: Annotated[str, typer.Option()],
    commit: Annotated[str, typer.Option()],
    pr: Annotated[int, typer.Option(min=1)],
    summary: Annotated[str, typer.Option()],
) -> None:
    send(
        ctx,
        "submit",
        {
            "task": task,
            "claim_id": claim_id,
            "commit": commit,
            "pr": pr,
            "summary": summary,
        },
    )


@app.command()
def hint(ctx: typer.Context, task: str, text: Annotated[str, typer.Option()]) -> None:
    """Append an in-repository handoff; review and commit it with your work."""

    def operation() -> dict[str, str]:
        root = context(ctx).path
        settings = read_settings(root)
        if not re.fullmatch(r"[0-9a-f]{12}", task):
            raise ValueError("Use a task ID returned by the broker")
        client, project = connection(ctx)
        if client.hub != settings.hub:
            raise ValueError("Hint checkout differs from the coordinating repository")
        snapshot = client.state()
        if not any(
            t["id"] == task
            for p in snapshot["projects"]
            if p["id"] == project
            for t in p["tasks"]
        ):
            raise ValueError("Task not found in this project")
        path = checked_path(root, f".hivemind/hints/{task}.md")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as stream:
            stream.write(
                f"\n## {datetime.now(timezone.utc).isoformat()}\n\n{text.strip()}\n"
            )
        return {"path": str(path), "next": "Review and commit the hint with your work."}

    perform(operation)


@broker.command("run")
def run_broker(
    config: Annotated[Path, typer.Option()] = Path(CONFIG),
) -> None:
    """Reconcile requests and standard work using the protected broker App token."""
    perform(lambda: execute_broker(config))


if __name__ == "__main__":
    app()
