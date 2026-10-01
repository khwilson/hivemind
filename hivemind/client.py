import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from .broker import ISSUE_PREFIX, dump
from .github_client import ApiError, GitHub, validate_repo
from .models import Action, Envelope, Payload
from .signing import sign


class Client:
    def __init__(
        self,
        hub: str,
        key: Path | None = None,
        wait: int = 300,
        api: GitHub | None = None,
    ):
        self.hub = validate_repo(hub).lower()
        self.api = api or GitHub()
        self.key, self.wait = key, wait
        self.branch = os.environ.get("HIVEMIND_STATE_BRANCH", "hivemind-state")

    def state(self) -> dict[str, Any]:
        return self.api.json_file(self.hub, "index.json", self.branch)

    def receipt(self, request_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{32}", request_id):
            raise ValueError("Use a request UUID returned by the CLI")
        try:
            receipt = self.api.json_file(
                self.hub, f"receipts/{request_id}.json", self.branch
            )
        except ApiError as exc:
            if exc.status != 404:
                raise
            return {"status": "pending", "request_id": request_id}
        return {"status": "accepted" if receipt["accepted"] else "rejected", **receipt}

    def send(
        self, project: str, action: Action, args: dict[str, Any]
    ) -> dict[str, Any]:
        now = int(time.time())
        payload = Payload(
            hub=self.hub,
            project=project,
            action=action,
            request_id=uuid.uuid4().hex,
            issued_at=now,
            expires_at=now + 86400,
            key_id="",
            args=args,
        )
        if self.key:
            envelope = sign(payload, self.key)
        else:
            if action not in ("add", "edit", "cancel", "prioritize", "note"):
                raise ValueError(
                    "Set HIVEMIND_KEY or --key to a registered signing key for agent operations"
                )
            payload.key_id = f"github:{self.api.get('/user')['id']}"
            envelope = Envelope(payload=payload)
        issue = self.api.request(
            f"/repos/{self.hub}/issues",
            "POST",
            {
                "title": f"{ISSUE_PREFIX}{action} {payload.request_id}",
                "body": dump(envelope.model_dump()),
            },
        )
        deadline = time.monotonic() + self.wait
        while self.wait and time.monotonic() < deadline:
            try:
                receipt = self.api.json_file(
                    self.hub, f"receipts/{payload.request_id}.json", self.branch
                )
            except ApiError as exc:
                if exc.status != 404:
                    raise
                time.sleep(min(15, max(0, deadline - time.monotonic())))
                continue
            if not receipt["accepted"]:
                raise ValueError(
                    f"Broker rejected issue #{issue['number']}: {receipt['message']}"
                )
            return {
                "status": "accepted",
                "issue": issue["number"],
                "request_id": payload.request_id,
                **receipt["result"],
            }
        return {
            "status": "pending",
            "issue": issue["number"],
            "url": issue["html_url"],
            "request_id": payload.request_id,
            "message": "No accepted receipt yet. You do not own a task until the broker accepts its claim.",
        }
