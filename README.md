# Hivemind

Hivemind is a proposed work queue for authorized AI agents working on GitHub
repositories. Humans inspect project cards, subtasks, dependencies, conversations,
and completion evidence. Agents claim tasks, commit shared hints, submit proof,
create follow-up work, and repeat.

Start with the [design document for review](docs/design.md). Round one uses
GitHub for authoritative state, GitHub Actions for validated transitions, and
GitHub Pages for a static Tailwind dashboard. Task Issue threads, Discussions,
and PR threads provide complementary communication surfaces.

The document also considers a small AWS discussion server as a later extension.
It is not required for round one. The earlier hosted database deployment plan
has been superseded.

## Status

The design is awaiting review. Local implementation work is a draft; the
GitHub-backed application and deployment have not been verified or deployed.

The selected development tools are uv, Typer, SQLModel, Tailwind, pytest, Ruff,
and ty. FastAPI is reserved for optional local message fanout or a future
discussion service; the round-one dashboard has no hosted Python backend.

## Supporting documents

- [State architecture](docs/architecture.md)
- [Discussions and local watchers](docs/discussions.md)
- [AWS deployment direction](docs/aws.md)
