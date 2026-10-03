"""Human-readable rendering of the broker's queue snapshot."""

from collections import Counter
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text


def print_status(snapshot: dict[str, Any], repo: str) -> None:
    console = Console()
    agents = {agent["id"]: agent["name"] for agent in snapshot.get("agents", [])}
    console.print(Text(repo, style="bold"))
    if not snapshot.get("projects"):
        console.print("No projects in the queue.")
    for project in snapshot.get("projects", []):
        wide = console.width >= 110
        counts: Counter[str] = Counter()
        table = Table(
            title=Text(
                f"{project.get('name', project['id'])} · queue revision "
                f"{project.get('revision', 1)}"
            ),
            show_lines=True,
        )
        columns = ("ID", "Task", "P", "Status")
        if wide:
            columns += ("Worker", "Depends on", "Rev")
        for column in columns:
            table.add_column(
                column,
                min_width=12 if column in ("ID", "Depends on") else None,
                overflow="fold",
                no_wrap=column in ("ID", "Depends on"),
            )
        for task in project.get("tasks", []):
            state = task["status"]
            if state == "queued":
                state = "blocked" if task.get("blocked_by") else "ready"
            counts[state] += 1
            agent = task.get("agent")
            worker = agents.get(agent, agent or "—")
            dependencies = "\n".join(task.get("dependencies", [])) or "—"
            revision = task.get("revision", 1)
            title = task["title"]
            if not wide:
                title += f"\nWorker: {worker} · Rev: {revision}"
                if task.get("dependencies"):
                    title += "\nDepends on: " + ", ".join(task["dependencies"])
            values = [task["id"], title, task["priority"], state]
            if wide:
                values += [worker, dependencies, revision]
            table.add_row(*[Text(str(value)) for value in values])
        console.print(table)
        console.print(
            ", ".join(
                f"{counts[state]} {state}"
                for state in ("active", "ready", "blocked", "done", "cancelled")
            )
            if counts
            else "No tasks yet."
        )
