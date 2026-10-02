"""ghapi adapter with Hivemind credential and error conventions."""

import base64
import json
import os
import re
import shutil
import subprocess
from functools import cached_property
from typing import Any
from urllib.parse import quote

import httpx2
from ghapi.core import GhApi

from .github_proof import verify
from .models import CheckPolicy


class ApiError(ValueError):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(f"GitHub {status}: {message}")


def error_message(response: httpx2.Response, token: str) -> str:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    message = body.get("message")
    if not isinstance(message, str):
        message = "Request failed"
    details = []
    errors = body.get("errors", [])
    if isinstance(errors, list):
        for error in errors[:10]:
            if isinstance(error, str):
                details.append(error)
            elif isinstance(error, dict):
                # Validation values and other response fields may contain secrets.
                fields = [error.get(key) for key in ("resource", "field", "code")]
                detail = ": ".join(field for field in fields if isinstance(field, str))
                if detail:
                    details.append(detail)
    if details:
        message += "; " + "; ".join(details)
    if token:
        message = message.replace(token, "[REDACTED]")
    return message[:2000]


def validate_repo(value: str) -> str:
    value = (
        value.strip()
        .removeprefix("https://github.com/")
        .rstrip("/")
        .removesuffix(".git")
    )
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value) or any(
        p in {".", ".."} for p in value.split("/")
    ):
        raise ValueError("Use a GitHub repository in owner/name form")
    return value


class GitHub:
    def __init__(self, token: str | None = None):
        self.token = (
            token
            if token is not None
            else os.environ.get("GH_TOKEN", os.environ.get("GITHUB_TOKEN", ""))
        )
        if token is None and not self.token and shutil.which("gh"):
            session = subprocess.run(
                ["gh", "auth", "token"], capture_output=True, text=True
            )
            if session.returncode == 0:
                self.token = session.stdout.strip()

    @cached_property
    def api(self) -> Any:
        # Resolve credentials ourselves: an ambient JWT or GH_HOST must not
        # override the repository-scoped broker token or destination.
        api: Any = GhApi(
            authenticate=False, gh_host="https://api.github.com", sync=True, timeout=30
        )
        api.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "User-Agent": "hivemind",
                "X-GitHub-Api-Version": "2026-03-10",
            }
        )
        if self.token:
            api.headers["Authorization"] = f"Bearer {self.token}"
        # The broker owns conflict retries; never replay writes at this layer.
        api.transport.retries = 0
        return api

    def request(self, path: str, method: str = "GET", data: Any = None) -> Any:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("GitHub requests require a relative API path")
        if data is not None:
            json.dumps(data, allow_nan=False)
        try:
            return self.api(path, method, data=data)
        except httpx2.HTTPStatusError as exc:
            message = error_message(exc.response, self.token)
            message += f" ({method.upper()} {path.split('?', 1)[0]})"
            raise ApiError(exc.response.status_code, message) from exc
        except httpx2.RequestError as exc:
            raise ApiError(503, "Connection failed") from exc

    def get(self, path: str) -> Any:
        return self.request(path)

    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        result = self.request(
            "/graphql", "POST", {"query": query, "variables": variables}
        )
        if result.get("errors"):
            raise ValueError(
                "GitHub GraphQL: " + "; ".join(e["message"] for e in result["errors"])
            )
        return result["data"]

    def pages(self, path: str, key: str | None = None) -> list[Any]:
        rows: list[Any] = []
        for page in range(1, 101):
            result = self.get(
                path + ("&" if "?" in path else "?") + f"per_page=100&page={page}"
            )
            batch = result[key] if key else result
            rows += batch
            if len(batch) < 100:
                return rows
        raise ValueError("GitHub pagination exceeded 10,000 items")

    def text_file(self, repo: str, path: str, ref: str) -> str:
        file = self.get(
            f"/repos/{validate_repo(repo)}/contents/{quote(path, safe='/')}?ref={quote(ref, safe='')}"
        )
        if file.get("encoding") != "base64":
            raise ValueError("File exceeds GitHub contents API size limit")
        return base64.b64decode(file["content"]).decode()

    def json_file(self, repo: str, path: str, ref: str) -> Any:
        return json.loads(self.text_file(repo, path, ref))

    def issue_is_unedited(self, repo: str, number: int) -> bool:
        owner, name = repo.split("/")
        result = self.graphql(
            "query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){issue(number:$number){lastEditedAt}}}",
            {"owner": owner, "name": name, "number": number},
        )
        issue = result["repository"]["issue"]
        return issue is not None and issue["lastEditedAt"] is None

    def verify(
        self, repo: str, commit: str, pr_number: int, required_checks: list[CheckPolicy]
    ) -> dict[str, Any]:
        validate_repo(repo)
        return verify(self, repo, commit, pr_number, required_checks)
