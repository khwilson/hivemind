"""Task transitions; callers apply changes to a copy before committing state."""

import hashlib
from copy import deepcopy
from typing import Any

from .models import (
    AddArgs,
    CancelArgs,
    ClaimArgs,
    EditArgs,
    Note,
    NoteArgs,
    OwnedArgs,
    PrioritizeArgs,
    Project,
    Settings,
    State,
    SubmitArgs,
    Task,
)

LEASE_SECONDS = 7200


class Queue:
    def __init__(self, state: State, settings: Settings):
        self.state = state
        for config in settings.projects:
            existing = next((p for p in state.projects if p.id == config.id), None)
            if existing is None:
                state.projects.append(Project(**config.model_dump()))
            else:
                for key, value in config.model_dump().items():
                    setattr(existing, key, deepcopy(getattr(config, key)))
        state.agents = [a.model_copy(deep=True) for a in settings.agents]
        self.allowed_projects = {p.id for p in settings.projects}

    def event(
        self,
        project: str,
        actor: str,
        action: str,
        now: int,
        task: str | None = None,
        detail: str = "",
    ) -> None:
        self.state.events.append(
            {
                "id": self.state.next_event_id,
                "project": project,
                "actor": actor,
                "action": action,
                "task": task,
                "detail": detail,
                "created": now,
            }
        )
        self.state.next_event_id += 1
        self.state.events = self.state.events[-1000:]

    def project(self, project_id: str) -> Project:
        project = next((p for p in self.state.projects if p.id == project_id), None)
        if project is None or project_id not in self.allowed_projects:
            raise ValueError("Project is not registered in trusted configuration")
        return project

    def task(self, project: Project, task_id: str) -> Task:
        task = next((t for t in project.tasks if t.id == task_id), None)
        if task is None:
            raise ValueError("Task does not belong to this project")
        return task

    def blockers(self, project: Project, task: Task) -> list[str]:
        refs = set(task.dependencies) | {
            t.id for t in project.tasks if t.parent == task.id
        }
        return [ref for ref in sorted(refs) if self.task(project, ref).status != "done"]

    def validate_graph(self, project: Project) -> None:
        edges = {t.id: set(t.dependencies) for t in project.tasks}
        for task in project.tasks:
            if task.parent:
                self.task(project, task.parent)
                edges[task.parent].add(task.id)
            for ref in task.dependencies:
                self.task(project, ref)
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(ref: str) -> None:
            if ref in visiting:
                raise ValueError("Dependencies and subtasks must not form a cycle")
            if ref in visited:
                return
            visiting.add(ref)
            for child in edges[ref]:
                visit(child)
            visiting.remove(ref)
            visited.add(ref)

        for ref in edges:
            visit(ref)

    def expire(self, now: int) -> None:
        agents = {a.id: a for a in self.state.agents if not a.revoked}
        for project in self.state.projects:
            for task in project.tasks:
                agent = agents.get(task.agent or "")
                if task.status == "active" and (
                    task.lease is None
                    or task.lease <= now
                    or agent is None
                    or project.id not in agent.projects
                    or "claim" not in agent.actions
                ):
                    self.clear_claim(task)
                    task.revision += 1
                    self.event(project.id, "broker", "lease_expired", now, task.id)

    @staticmethod
    def clear_claim(task: Task) -> None:
        task.status, task.agent, task.claim_id, task.lease = "queued", None, None, None

    def owned(self, project: Project, args: OwnedArgs, actor: str, now: int) -> Task:
        task = self.task(project, args.task)
        if (
            task.status != "active"
            or task.agent != actor
            or task.claim_id != args.claim_id
            or task.lease is None
            or task.lease <= now
        ):
            raise ValueError(
                "An active unexpired claim with matching agent and claim ID is required"
            )
        return task

    def apply(
        self,
        project_id: str,
        action: str,
        args: dict[str, Any],
        actor: str,
        request_id: str,
        now: int,
        proof: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = self.project(project_id)
        self.expire(now)
        if action == "add":
            data = AddArgs.model_validate(args)
            if not data.title.strip() or not data.criteria.strip():
                raise ValueError("Title and acceptance criteria must not be blank")
            if data.parent and self.task(project, data.parent).status in (
                "done",
                "cancelled",
            ):
                raise ValueError("Cannot add a subtask to a finished parent")
            task_id = hashlib.sha256(request_id.encode()).hexdigest()[:12]
            if any(t.id == task_id for p in self.state.projects for t in p.tasks):
                raise ValueError("Task ID collision; submit a new request")
            task = Task(
                id=task_id, project=project.id, created=now, **data.model_dump()
            )
            project.tasks.append(task)
            self.validate_graph(project)
            project.tasks.sort(key=lambda t: t.priority)
            project.revision += 1
            self.event(project.id, actor, "task_created", now, task.id, task.title)
            return {
                "id": task.id,
                "revision": task.revision,
                "queue_revision": project.revision,
            }
        if action in ("edit", "cancel"):
            edit = (
                EditArgs.model_validate(args)
                if action == "edit"
                else CancelArgs.model_validate(args)
            )
            task = self.task(project, edit.task)
            if task.revision != edit.expected_revision:
                raise ValueError("Task revision conflict; refresh before editing")
            if task.status in ("done", "cancelled"):
                raise ValueError("Finished tasks are immutable; create a follow-up")
            if action == "cancel":
                self.clear_claim(task)
                task.status = "cancelled"
            else:
                assert isinstance(edit, EditArgs)
                updates = edit.model_dump(
                    exclude={"task", "expected_revision", "release_claim"},
                    exclude_unset=True,
                )
                if not updates:
                    raise ValueError("Provide at least one edited field")
                if any(
                    value is None and key != "parent" for key, value in updates.items()
                ):
                    raise ValueError("Only the parent field can be cleared with null")
                if any(isinstance(v, str) and not v.strip() for v in updates.values()):
                    raise ValueError("Edited text must not be blank")
                if task.status == "active":
                    if not edit.release_claim:
                        raise ValueError(
                            "Explicit --release-claim is required to edit active work"
                        )
                    self.clear_claim(task)
                for key, value in updates.items():
                    setattr(task, key, value)
                if task.parent and self.task(project, task.parent).status in (
                    "done",
                    "cancelled",
                ):
                    raise ValueError("Parent is already finished")
                self.validate_graph(project)
            task.revision += 1
            project.revision += 1
            self.event(project.id, actor, f"task_{action}ed", now, task.id)
            return {"task": task.model_dump(), "queue_revision": project.revision}
        if action == "claim":
            data = ClaimArgs.model_validate(args)
            candidates = [
                t
                for t in project.tasks
                if t.status == "queued" and not self.blockers(project, t)
            ]
            task = next(
                (t for t in candidates if data.task is None or t.id == data.task), None
            )
            if task is None:
                return {"task": None}
            task.status, task.agent, task.claim_id, task.lease = (
                "active",
                actor,
                request_id,
                now + LEASE_SECONDS,
            )
            task.revision += 1
            self.event(project.id, actor, "task_claimed", now, task.id)
            return {"task": task.model_dump()}
        if action in ("heartbeat", "release", "submit"):
            owned = (
                SubmitArgs.model_validate(args)
                if action == "submit"
                else OwnedArgs.model_validate(args)
            )
            task = self.owned(project, owned, actor, now)
            if action == "heartbeat":
                task.lease = now + LEASE_SECONDS
                self.event(project.id, actor, "claim_renewed", now, task.id)
                return {"lease": task.lease, "claim_id": task.claim_id}
            if action == "release":
                self.clear_claim(task)
                task.revision += 1
                self.event(project.id, actor, "task_released", now, task.id)
                return {"status": "queued"}
            if proof is None or self.blockers(project, task):
                raise ValueError(
                    "Verified proof and completed dependencies/subtasks are required"
                )
            task.status, task.proof, task.lease = (
                "done",
                {**proof, "task_revision": task.revision},
                None,
            )
            task.revision += 1
            self.event(project.id, actor, "task_completed", now, task.id)
            return {"status": "done", "proof": task.proof}
        if action == "prioritize":
            data = PrioritizeArgs.model_validate(args)
            if data.expected_revision != project.revision:
                raise ValueError("Queue revision conflict; refresh before prioritizing")
            if len(data.tasks) != len(set(data.tasks)) or set(data.tasks) != {
                t.id for t in project.tasks
            }:
                raise ValueError("Ordering must list every project task exactly once")
            project.tasks = [self.task(project, ref) for ref in data.tasks]
            project.revision += 1
            self.event(project.id, actor, "queue_prioritized", now)
            return {"tasks": data.tasks, "queue_revision": project.revision}
        if action == "note":
            note = NoteArgs.model_validate(args)
            task = self.task(project, note.task)
            task.notes.append(Note(actor=actor, text=note.text, created=now))
            self.event(project.id, actor, "note_added", now, task.id, note.text)
            return {"id": task.id}
        raise ValueError("Unsupported action")

    def snapshot(self) -> dict[str, Any]:
        result = self.state.model_dump(
            exclude={"receipts", "processed_issues", "request_ids", "generation_ids"}
        )
        for data, project in zip(result["projects"], self.state.projects, strict=True):
            data["required_checks"] = [c.name for c in project.required_checks]
            data["agents"] = [
                a.model_dump(exclude={"public_key", "github_id", "projects", "actions"})
                for a in self.state.agents
                if project.id in a.projects
            ]
            data["events"] = [
                e for e in reversed(self.state.events) if e["project"] == project.id
            ][:100]
            for task_data, task in zip(data["tasks"], project.tasks, strict=True):
                task_data["blocked_by"] = self.blockers(project, task)
        return result
