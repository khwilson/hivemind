# Hivemind

Hivemind provides a standalone CLI for GitHub repository work queues, setup,
agent instructions, and mathematics follow-up work. Agents claim tasks, commit
shared hints, submit proof, create follow-up work, and repeat. The planned viewer
will let humans edit queues and inspect project cards, dependencies, and evidence.

```sh
uv tool install 'git+https://github.com/khwilson/hivemind.git@v0.1.0'
hivemind --help
```

See the [CLI and deployment instructions](docs/cli.md) for initialization,
GitHub App setup, agent registration, and the work loop. `uvx --from` also runs
the tool without a persistent installation.

Start with the [design document for review](docs/design.md). Round one uses
GitHub for authoritative state, GitHub Actions for validated transitions, and
GitHub Pages for a static Tailwind dashboard. Task Issue threads, Discussions,
and PR threads provide complementary communication surfaces.

Each project keeps its queue in its target repository. Branch rules protect the
state and coordinator, and a broker App credential is restricted to trusted
Actions runs. The dashboard aggregates repositories without a central queue.

The document also considers a small AWS discussion server as a later extension.
It is not required for round one. The earlier hosted database deployment plan
has been superseded.

The [deliverable requirements](docs/deliverables.md) define four parts:

- A standalone uv-installable Typer CLI for setup, diagnosis, upgrades, and agent
  work, replacing the earlier local-server installation flow.
- Bundled, versioned `AGENTS.md` and `SKILL.md` templates that preserve existing
  repository instructions and customized skills.
- A static queue editor whose changes pass through the broker, with revisions,
  conflict handling, and visible request receipts.
- Configured standard work, including mathematics generalization reviews after
  relevant changes, with provenance, deduplication, and recursion limits.

## Status

The first CLI implementation includes repeatable installation, five bundled
skills, setup plans and settings application, diagnostics, signed queue requests,
revision-checked edits, and broker-generated mathematics review tasks. Local
tests and package installation are verified. Live GitHub permissions and broker
deployment still need a disposable-repository smoke test. The viewer's GitHub
editor, Pages deployment, and conversation watcher remain future work.

The selected development tools are uv, Typer, SQLModel, Tailwind, pytest, Ruff,
and ty. FastAPI is reserved for optional local message fanout or a future
discussion service; the round-one dashboard has no hosted Python backend.

## Supporting documents

- [State architecture](docs/architecture.md)
- [CLI and deployment instructions](docs/cli.md)
- [Deliverables and standard work](docs/deliverables.md)
- [Discussions and local watchers](docs/discussions.md)
- [AWS deployment direction](docs/aws.md)
