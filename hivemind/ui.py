"""Loopback-only web interface backed by the installed Hivemind CLI."""

import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import webbrowser
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

import typer
import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field

from .github_client import validate_repo
from .models import AddArgs, CancelArgs, EditArgs, Model, NoteArgs, PrioritizeArgs


class Command(Model):
    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    project: str = Field(pattern=r"^[a-z0-9_-]{1,64}$")
    action: Literal["add", "edit", "cancel", "prioritize", "note", "kick"]
    args: dict[str, Any] = Field(default_factory=dict)


def command_args(command: Command) -> list[str]:
    """Build an allowlisted argument vector, never a shell command."""
    if command.action == "kick":
        if command.args:
            raise ValueError("kick does not accept arguments")
        return ["kick"]
    schemas = {
        "add": AddArgs,
        "edit": EditArgs,
        "cancel": CancelArgs,
        "prioritize": PrioritizeArgs,
        "note": NoteArgs,
    }
    data = (
        schemas[command.action]
        .model_validate(command.args)
        .model_dump(exclude_unset=True)
    )
    references = [data.get("task"), data.get("parent")]
    references.extend(data.get("dependencies") or [])
    references.extend(data.get("tasks") or [])
    if any(
        value is not None and not re.fullmatch(r"[0-9a-f]{12}", value)
        for value in references
    ):
        raise ValueError("Use task IDs returned by the broker")
    argv = ["task", command.action]
    if "task" in data:
        argv.append(data.pop("task"))
    if command.action == "prioritize":
        argv.extend(data.pop("tasks"))
    for name, value in data.items():
        if name == "expected_revision":
            argv.extend(["--revision", str(value)])
        elif name == "dependencies":
            if not value and command.action == "edit":
                argv.append("--clear-dependencies")
            for dependency in value or []:
                argv.extend(["--depends-on", dependency])
        elif name == "parent" and value is None:
            if command.action == "edit":
                argv.append("--clear-parent")
        elif name == "release_claim":
            if value:
                argv.append("--release-claim")
        elif value is not None:
            argv.extend(["--" + name.replace("_", "-"), str(value)])
    return argv


class Runner:
    def __init__(self, root: Path, repo: str):
        self.root = root
        self.repo = validate_repo(repo).lower()

    def run(self, arguments: list[str], project: str | None = None) -> dict[str, Any]:
        argv = [
            sys.executable,
            "-I",
            "-m",
            "hivemind.cli",
            "--path",
            str(self.root),
            "--repo",
            self.repo,
            "--wait",
            "0",
        ]
        if project:
            argv.extend(["--project", project])
        # This is a human editor. Never inherit an ambient worker signing key or
        # an environment variable that redirects requests to another queue.
        env = {k: v for k, v in os.environ.items() if not k.startswith("HIVEMIND_")}
        result = subprocess.run(
            [*argv, *arguments],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        if result.returncode:
            try:
                receipt = json.loads(result.stdout)
            except ValueError:
                receipt = {}
            if receipt.get("status") == "rejected":
                return receipt
            raise ValueError(result.stderr.strip() or "Hivemind command failed")
        return json.loads(result.stdout)


def create_app(runner: Runner, token: str, port: int) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    jobs: dict[str, dict[str, Any]] = {}
    lock = threading.Lock()
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    @app.middleware("http")
    async def local_session(request: Request, call_next: Any) -> Response:
        host = request.headers.get("host", "")
        origin = request.headers.get("origin")
        if host not in allowed_hosts or (
            origin is not None and origin != f"http://{host}"
        ):
            return JSONResponse({"error": "Local UI origin required"}, status_code=403)
        if request.url.path.startswith("/api/") and not secrets.compare_digest(
            request.headers.get("x-hivemind-session", ""), token
        ):
            return JSONResponse(
                {"error": "Open the session URL printed by hivemind ui"},
                status_code=403,
            )
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'"
        )
        return response

    @app.exception_handler(ValueError)
    async def command_error(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=400)

    @app.exception_handler(subprocess.SubprocessError)
    async def process_error(
        request: Request, exc: subprocess.SubprocessError
    ) -> JSONResponse:
        return JSONResponse(
            {
                "error": "Command timed out. Check GitHub Issues before retrying a write."
            },
            status_code=504,
        )

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        snapshot = runner.run(["status", "--json"])
        return {**snapshot, "repo": runner.repo, "actor": runner.run(["whoami"])}

    def execute(command: Command, argv: list[str]) -> None:
        try:
            result = runner.run(argv, command.project)
            update = {"status": "finished", "result": result}
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            update = {"status": "failed", "error": str(exc)}
        with lock:
            jobs[command.id].update(update)

    @app.post("/api/commands", status_code=202)
    def submit(command: Command, background: BackgroundTasks) -> dict[str, Any]:
        argv = command_args(command)
        with lock:
            if command.id in jobs:
                if jobs[command.id]["command"] != command.model_dump():
                    raise HTTPException(409, "Command ID already used for another edit")
                return {"id": command.id}
            if len(jobs) >= 1000:
                raise HTTPException(429, "Session full; restart hivemind ui")
            jobs[command.id] = {"status": "running", "command": command.model_dump()}
        background.add_task(execute, command, argv)
        return {"id": command.id}

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str) -> dict[str, Any]:
        with lock:
            if job_id not in jobs:
                raise HTTPException(404, "Job is not in this UI session")
            return dict(jobs[job_id])

    @app.get("/api/requests/{request_id}")
    def receipt(request_id: str) -> dict[str, Any]:
        return runner.run(["request", "show", request_id])

    @app.get("/{asset:path}")
    def asset_file(asset: str) -> Response:
        name = asset or "index.html"
        types = {
            "index.html": "text/html",
            "app.js": "text/javascript",
            "style.css": "text/css",
        }
        if name not in types:
            raise HTTPException(404)
        return Response(
            files("hivemind.web").joinpath(name).read_bytes(), media_type=types[name]
        )

    return app


def serve(root: Path, repo: str, port: int, browser: bool) -> None:
    token = secrets.token_urlsafe(32)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))
        sock.listen(128)
        actual_port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{actual_port}/#session={token}"
        app = create_app(Runner(root, repo), token, actual_port)
        typer.echo(f"Hivemind UI: {url}\nUses your local GitHub login. Ctrl+C to stop.")
        if browser:
            timer = threading.Timer(1, webbrowser.open, args=(url,))
            timer.daemon = True
            timer.start()
        server = uvicorn.Server(
            uvicorn.Config(app, access_log=False, log_level="warning")
        )
        server.run(sockets=[sock])
