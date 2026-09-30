import base64
import json
import os
import re
import shutil
import subprocess
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .models import CheckPolicy


class ApiError(ValueError):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(f"GitHub {status}: {message}")


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

    def request(self, path: str, method: str = "GET", data: Any = None) -> Any:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "hivemind",
            "X-GitHub-Api-Version": "2026-03-10",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = Request(
            "https://api.github.com" + path,
            headers=headers,
            method=method,
            data=json.dumps(data, allow_nan=False).encode()
            if data is not None
            else None,
        )
        try:
            with urlopen(req, timeout=30) as response:
                content = response.read()
                return json.loads(content) if content else None
        except HTTPError as exc:
            try:
                message = json.load(exc).get("message", "Request failed")
            except (ValueError, AttributeError):
                message = "Request failed"
            raise ApiError(exc.code, message) from exc
        except URLError as exc:
            raise ApiError(503, f"Connection failed: {exc.reason}") from exc

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
        if not re.fullmatch(r"[0-9a-fA-F]{40}", commit) or pr_number < 1:
            raise ValueError("Proof requires a full commit SHA and positive PR number")
        commit = commit.lower()
        path = f"/repos/{repo}/pulls/{pr_number}"
        pr = self.get(path)
        if (
            pr["base"]["repo"]["full_name"].lower() != repo.lower()
            or pr["head"]["sha"] != commit
        ):
            raise ValueError(
                "PR repository or current head does not match submitted proof"
            )
        if pr["state"] == "closed" and not pr.get("merged"):
            raise ValueError("PR was closed without merging")
        runs = self.pages(
            f"/repos/{repo}/commits/{commit}/check-runs?filter=latest", "check_runs"
        )
        statuses = self.get(f"/repos/{repo}/commits/{commit}/status")
        if not runs or any(
            c["status"] != "completed" or c.get("conclusion") != "success" for c in runs
        ):
            raise ValueError("Every reported GitHub check must complete successfully")
        if statuses.get("total_count", 0) and statuses["state"] != "success":
            raise ValueError("GitHub commit statuses have not all passed")
        for policy in required_checks:
            if not any(
                c["name"] == policy.name and c["app"]["id"] == policy.app_id
                for c in runs
            ):
                raise ValueError(
                    f"Missing successful trusted check: {policy.name} (app {policy.app_id})"
                )
        latest = self.get(path)
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
