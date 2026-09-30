# Hivemind development

Hivemind coordinates authorized AI agents working on GitHub repositories.
Maintain atomic claims, repository-scoped authorization, dependency ordering,
and broker-verified GitHub proof before automatically marking work done.

## Stack

- Python dependencies and commands: uv, with a committed `uv.lock`.
- Authoritative queue: GitHub state branch, updated by trusted Actions workflows.
- Each project coordinates in its target repository; the dashboard aggregates
  repositories. State writes use a dedicated broker App protected by branch
  rules and a restricted Actions environment.
- Website: static GitHub Pages dashboard.
- Optional local fanout or future discussion service: FastAPI and Uvicorn.
- Typed state models and any future discussion database: SQLModel.
- Agent CLI: Typer (`hivemind`).
- Website styling: Tailwind CSS, compiled from `hivemind/web/input.css`.
- Tests: pytest.

## Required checks

Always run these checks before finishing work on this project:

```sh
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```

Ruff uses the standard isort import rules and Black-compatible formatter
defaults (88 columns, double quotes, four-space indentation). Fix findings;
do not globally disable checks to make a change pass.

When changing the web interface, also run:

```sh
npm run build:css
npm run check
```

Keep generated CSS in the package. Preserve existing target-repository
AGENTS.md rules when installing the marked Hivemind workflow section. Keep
agent handoff hints committed inside the governed GitHub repository. Do not
store credentials in documentation, hints, or source control.

The canonical proposal is `docs/design.md`. The per-project architecture is
approved; remaining design decisions await human review and implementation files
are drafts. Round one uses GitHub, with no hosted database.
A small AWS discussion service is a possible later extension, not a current
deployment requirement. Keep proposal statements distinct from verified features.
