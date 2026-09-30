# GitHub-backed coordination

Hivemind coordinates independently operated agents through GitHub. Each project
names exactly one target repository. A central hub repository holds authorization
and task state; target repositories hold implementation code, pull requests,
repository instructions, and committed handoff hints. A static dashboard reads
GitHub. No persistent Hivemind API server or database is required.

This document records the intended architecture. The companion
[Discussions design](discussions.md) describes agent communication and proposed
watcher extensions. It incorporates the user-provided four-page design note
`hivemind.pdf`, “Git-Backed AI Agent Coordination Design.” That local document is
background input, not a repository dependency. Its claims about prior tools and
their success have not been independently established here.

## Ownership and storage

| Location | Contents | Writer |
| --- | --- | --- |
| Hub default branch | Broker, project registry, public keys, permissions, CI policies | Trusted maintainers |
| Hub `hivemind-state` branch | Queue, tasks, claims, proofs, receipts, dashboard index | Trusted broker |
| Hub Issues | Signed agent requests and permitted human requests | Individual GitHub users |
| GitHub Discussions | Questions, decisions, blockers, milestones, handoffs | Humans and their agents |
| Target default and task branches | Code, `AGENTS.md`, `.hivemind/` configuration and hints | Target contributors |
| GitHub Pages | HTML, compiled Tailwind CSS, JavaScript | Deployment workflow |

The state branch is an **orphan branch with a named ref**, not a detached HEAD.
Its layout separates objects for readable history and economical updates:

```text
hivemind-state/
  queue.json
  tasks/
    <task-id>/
      task.json
      claim.json
      proof.json
  receipts/
    <request-uuid>.json
  index.json
```

`task.json` contains the project, acceptance criteria, priority, parent, and
dependencies. `claim.json` contains the lease owner, fencing identifier, and
expiry. `proof.json` records verified GitHub evidence. `queue.json` is the
manifest and ordering data. `index.json` is a derived dashboard snapshot, not a
second source of authority. Receipts record request outcomes and prevent replay.
Absent claims and proofs must have an unambiguous representation in the schema.
All files affected by a transition are committed together.

Splitting files does **not** eliminate contention on the shared branch ref. It
also does not make independent agents safe to merge arbitrary claims. A single
broker and validated optimistic updates enforce the coordination invariants.

Central storage avoids a broker installation and privileged write credential in
every target repository. The tradeoff is shared hub visibility: task descriptions
about a private target are public if stored in a public hub. Use a private hub for
private coordination, or separate hubs where access policies differ.

## Requests and authorization

Each agent has an Ed25519 key pair. The private key stays with its operator; the
trusted registry stores the public key, key identifier, stable GitHub actor ID,
permitted projects, and capabilities. Several agents may use the same human's
GitHub identity while retaining separate agent keys. Git author names and email
addresses are descriptive metadata, not authentication.

A signed request binds the protocol version, hub repository, target project,
action, complete arguments, request UUID, timestamps, and key identifier. The
broker validates a strict schema and canonical signature encoding, verifies the
signature, and compares the request identity with the issue author's GitHub ID.
It rejects incorrect scope, expired requests, revoked keys, and replay. It reads
authorization from the trusted default branch, never from the state branch or a
request payload.

Explicitly configured maintainers may issue unsigned `add`, `prioritize`, and
`note` requests under their authenticated GitHub actor IDs. This exception is
limited to those capabilities and configured projects. It does not let an issue
author edit authorization, claim an agent identity, or fabricate completion.

Agents require access to create hub issues, not hub contents or workflow write
access. Target code permissions are separate. Anyone able to replace the hub
broker or registry belongs to the trusted administrative boundary. Branch
protection, rulesets, and credentials must reflect that boundary; signatures
cannot compensate for an agent being able to replace its verifier.

## Broker and atomic transitions

The broker runs from trusted default-branch code on issue creation or editing,
with a scheduled sweeper and manual recovery trigger. GitHub documents that
issue-triggered workflows use the default branch and require the workflow file
there. [Workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)

Each run reconciles the durable request inbox rather than assuming that one
workflow run corresponds to one request. Workflow concurrency uses a common
group with `cancel-in-progress: false`. Pending runs can still be replaced under
the default concurrency behavior, so reconciliation is required for correctness.
[Workflow concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)

For each transition, the broker:

1. Reads the current state ref and trusted configuration.
2. Validates the request, current authorization, task graph, and any lease.
3. Obtains required GitHub evidence when processing completion.
4. Revalidates mutable preconditions, including lease expiry.
5. Creates a commit with exactly the observed state tip as its parent, including
   the receipt and every affected state file.
6. Updates the branch with `force: false`.
7. On conflict, rereads state and recomputes the transition with bounded,
   jittered backoff. It never blindly rebases a previously accepted claim.
8. After the commit succeeds, updates the request issue's presentation.

GitHub's non-forced ref update requires a fast-forward update. Competing commits
with the same observed parent therefore cannot both replace the tip without a
fresh read and validation. [Git references API](https://docs.github.com/en/rest/git/refs)

The receipt and transition are one commit, so a crash before issue acknowledgement
cannot apply the request twice. Issue comments and closure are retryable outputs,
not evidence that a transition committed. The CLI must observe an accepted
receipt before reporting success; a timeout reports a pending request.

Do not interpolate issue or Discussion text into shell commands. The broker must
not check out, import, or execute request-controlled code. CI for target pull
requests runs separately from the privileged state broker.

## Claims, ordering, and dependency safety

Claims last 120 minutes and carry a random fencing identifier. Heartbeat,
release, and proof requests must match that identifier and the current owner.
An expired agent cannot operate on a replacement claim, even when the same
agent later claims the same task again. Renew comfortably before expiry to allow
for Actions queue latency; an unconfirmed renewal does not extend the lease.

The broker chooses ready work in a deterministic priority order. Dependencies
and children must be complete before a parent is ready. References stay inside
the project, and cycle validation accounts for both explicit dependencies and
the implicit requirement that parents wait for children. Creating a child for
an active parent requires the parent to be released before it can be worked
again under the updated prerequisites.

GitHub state is authoritative; local caches and Discussion messages cannot
grant ownership. Operators can keep frequent communication inside their local
swarm while posting consequential coordination to Discussions. This supports
the design note's intended scale of roughly five humans with three agents each
without requiring a shared Redis, database, or model-provider account.

## Verified completion

Proof identifies a full commit SHA, pull request, and explanation of acceptance
criteria. The broker verifies the configured target repository, current PR head,
permitted PR state, and required successful checks from configured issuers. It
refetches the PR and rechecks the current lease and task prerequisites before
committing completion. Evidence records retain the commit, PR, check identities,
results, verification time, and configuration revision used.

Matching a check name is insufficient. Even a GitHub Actions app ID does not
establish that a workflow is trustworthy if the contributing agent can rewrite
that workflow to pass unconditionally. Target repositories must govern their CI
definitions and required checks. Verified CI also does not independently prove
arbitrary acceptance prose, merge the PR, or prevent later edits to an open PR.
Projects whose dependents require integrated code must configure a completion
policy that verifies integration before releasing those dependents.

The hub workflow token writes hub state. Its permissions are restricted to the
repository containing the workflow; an optional read-only `GH_PROOF_TOKEN`
provides access to private targets' pull requests and checks. Keep credentials in
GitHub secrets and local credential storage, never in tasks or hints.
[GitHub Actions token scope](https://docs.github.com/en/enterprise-cloud%40latest/actions/concepts/security/github_token)

## Dashboard, installation, and recovery

GitHub Actions builds and deploys a static Pages shell. The browser fetches the
hub index using GitHub's API. A private workspace token remains in the browser
session and is not embedded in the deployment. Render task and Discussion text
as untrusted content. Pages hosts static HTML, CSS, and JavaScript; runtime state
comes from GitHub. [GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)

Installing into a target checkout preserves existing `AGENTS.md` rules and
updates only Hivemind's marked section. Committed `.hivemind/` configuration
points to the hub and project; committed hints preserve findings and handoffs
alongside the code. Installation does not implicitly grant repository access.

History supports inspection and recovery, but a blind reset can resurrect old
claims and erase replay receipts. Repair state through an explicit validated
administrative transition, preserving audit history and invalidating affected
claims. Rebuilding the dashboard index is safe because it is derived from
authoritative state.
