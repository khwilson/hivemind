"""Validated file schemas. GitHub is the database; no ORM tables are created."""

from typing import Any, Literal

from pydantic import Field, StrictInt, field_validator, model_validator
from sqlmodel import SQLModel
from sqlmodel.main import SQLModelConfig


class Model(SQLModel):
    model_config = SQLModelConfig(extra="forbid")


class CheckPolicy(Model):
    name: str = Field(min_length=1, max_length=200)
    app_id: StrictInt = Field(gt=0)


class ProjectConfig(Model):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,64}$")
    name: str = Field(min_length=1, max_length=120)
    repo: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    description: str = Field(default="", max_length=10000)
    required_checks: list[CheckPolicy] = Field(min_length=1)


class Agent(Model):
    id: str = Field(pattern=r"^[0-9a-f]{16}$")
    name: str
    github_id: StrictInt = Field(gt=0)
    public_key: str
    projects: list[str]
    actions: list[str] = Field(
        default_factory=lambda: [
            "claim",
            "heartbeat",
            "release",
            "submit",
            "add",
            "note",
        ]
    )
    revoked: bool = False


class Settings(Model):
    version: Literal[1] = 1
    hub: str
    state_branch: str = "hivemind-state"
    maintainers: list[StrictInt]
    agents: list[Agent] = Field(default_factory=list)
    projects: list[ProjectConfig] = Field(min_length=1, max_length=1)

    @field_validator("hub")
    @classmethod
    def hub_name(cls, value: str) -> str:
        from .github import validate_repo

        return validate_repo(value).lower()

    @model_validator(mode="after")
    def repository_scope(self) -> "Settings":
        if self.state_branch != "hivemind-state":
            raise ValueError("This release uses the protected hivemind-state branch")
        if self.projects[0].repo.lower() != self.hub:
            raise ValueError("Project and coordinating repository must match")
        if len({a.id for a in self.agents}) != len(self.agents):
            raise ValueError("Agent key IDs must be unique")
        return self


Action = Literal[
    "claim",
    "heartbeat",
    "release",
    "submit",
    "add",
    "edit",
    "cancel",
    "prioritize",
    "note",
]


class Payload(Model):
    version: Literal[1] = 1
    hub: str
    project: str
    action: Action
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    issued_at: StrictInt
    expires_at: StrictInt
    key_id: str
    args: dict[str, Any] = Field(default_factory=dict)


class Envelope(Model):
    payload: Payload
    signature: str = ""


class Note(Model):
    actor: str
    text: str
    created: int


class Task(Model):
    id: str
    project: str
    title: str
    criteria: str
    parent: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    priority: int = 2
    status: Literal["queued", "active", "done", "cancelled"] = "queued"
    agent: str | None = None
    claim_id: str | None = None
    lease: int | None = None
    proof: dict[str, Any] | None = None
    notes: list[Note] = Field(default_factory=list)
    created: int
    revision: int = 1
    provenance: dict[str, Any] | None = None


class Project(ProjectConfig):
    tasks: list[Task] = Field(default_factory=list)
    revision: int = 1


class Receipt(Model):
    request_id: str
    issue: int
    accepted: bool
    message: str
    result: dict[str, Any] = Field(default_factory=dict)
    created: int
    payload_hash: str
    config_sha: str
    envelope: dict[str, Any] | None = None
    github_id: int | None = None


class State(Model):
    version: Literal[1] = 1
    projects: list[Project] = Field(default_factory=list)
    agents: list[Agent] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    receipts: dict[str, Receipt] = Field(default_factory=dict)
    processed_issues: dict[str, str] = Field(default_factory=dict)
    request_ids: list[str] = Field(default_factory=list)
    next_event_id: int = 1
    standard_cursor: str | None = None
    generation_ids: list[str] = Field(default_factory=list)


class AddArgs(Model):
    title: str = Field(min_length=1, max_length=200)
    criteria: str = Field(min_length=1, max_length=10000)
    parent: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    priority: StrictInt = Field(default=2, ge=1, le=3)


class ClaimArgs(Model):
    task: str | None = None


class OwnedArgs(Model):
    task: str
    claim_id: str


class SubmitArgs(OwnedArgs):
    commit: str = Field(pattern=r"^[0-9a-fA-F]{40}$")
    pr: StrictInt = Field(gt=0)
    summary: str = Field(min_length=1, max_length=10000)


class PrioritizeArgs(Model):
    tasks: list[str]
    expected_revision: StrictInt = Field(gt=0)


class NoteArgs(Model):
    task: str
    text: str = Field(min_length=1, max_length=10000)


class EditArgs(Model):
    task: str
    expected_revision: StrictInt = Field(gt=0)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    criteria: str | None = Field(default=None, min_length=1, max_length=10000)
    dependencies: list[str] | None = None
    parent: str | None = None
    priority: StrictInt | None = Field(default=None, ge=1, le=3)
    release_claim: bool = False


class CancelArgs(Model):
    task: str
    expected_revision: StrictInt = Field(gt=0)
