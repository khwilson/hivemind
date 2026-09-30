# GitHub-backed coordination

Hivemind coordinates independently operated agents through GitHub. Each project
names exactly one target repository, which also hosts its coordination state,
requests, authorization, broker workflow, code, pull requests, repository
instructions, and committed handoff hints. A static dashboard aggregates selected
repositories through GitHub. No persistent Hivemind API or database is required.
This per-project arrangement is the approved architecture; the
[canonical design](design.md) specifies its branch rules and broker credentials.
The [deliverable requirements](deliverables.md) specify the standalone setup and
agent CLI, versioned instruction/skill bundle, editable viewer, and standard work.

This document records the intended architecture. The companion
[Discussions design](discussions.md) describes agent communication and proposed
watcher extensions. It incorporates the user-provided four-page design note
`hivemind.pdf`, “Git-Backed AI Agent Coordination Design.” That local document is
background input, not a repository dependency. Its claims about prior tools and
their success have not been independently established here.

## Ownership and storage

| Location | Contents | Writer |
| --- | --- | --- |
| Project default branch | Broker, local registry, public keys, permissions, CI policies | Contributors through protected PRs; trusted owners review coordination changes |
| Project `hivemind-state` branch | Queue, tasks, claims, proofs, receipts, dashboard index | Trusted broker App |
| Project Issues | Signed agent requests and permitted human requests | Individual GitHub users |
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

Every project installs its own broker workflow, registry, rulesets, and protected
App credential. This adds setup work but separates authorization, visibility,
contention, and recovery. The dashboard combines derived indexes without owning
state or granting access. Task metadata has the target repository's visibility;
never bake private metadata into public dashboard assets. Cross-project
dependencies and atomic transitions are outside round one.

## Requests and authorization

Each agent has an Ed25519 key pair. The private key stays with its operator; the
trusted registry stores the public key, key identifier, stable GitHub actor ID,
permitted projects, and capabilities. Several agents may use the same human's
GitHub identity while retaining separate agent keys. Git author names and email
addresses are descriptive metadata, not authentication.

A signed request binds the protocol version, coordinating target repository, project,
action, complete arguments, request UUID, timestamps, and key identifier. The
broker validates a strict schema and canonical signature encoding, verifies the
signature, and compares the request identity with the issue author's GitHub ID.
It rejects incorrect scope, expired requests, revoked keys, and replay. It reads
authorization from the trusted default branch, never from the state branch or a
request payload.

Explicitly configured maintainers may issue unsigned `add`, `edit`, `prioritize`,
`cancel`, and `note` requests under their authenticated GitHub actor IDs. This
exception is limited to those capabilities and configured projects. It does not let an issue
author edit authorization, claim an agent identity, or fabricate completion.
Reject edited unsigned requests unless their author/edit provenance can be
verified. Preserve the accepted request and observed identity with its receipt.
An agent using a maintainer's credential inherits its human capabilities.

Agents may write ordinary work branches and create request Issues. They cannot
administer settings, bypass coordination rules, or merge coordination changes
without trusted review. Protect broker code, dependencies, workflow definitions,
registry, CI policy, and CODEOWNERS itself on the default branch.
Protect standard-work rules and their executable or prompt dependencies as
reviewed inputs to automatic task generation.

Restrict state branch creation and updates to the dedicated broker App. Keep
force-push and deletion prohibitions in separate rulesets with no App bypass;
bootstrap the orphan branch before enabling creation restrictions. Do not give
the generic Actions identity or agent accounts a state bypass. The broker App
has no default-branch bypass or administration permission.
[Rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)

Store the App private key in a coordination environment permitting only the exact
trusted default branch, excluding tags. Mint short-lived installation tokens
scoped to this repository. Branch protection does not stop other branches from
running workflows, and read-only default GITHUB_TOKEN permissions are not a hard
ceiling. Environment restrictions protect the privileged credential; trusted
broker code must also avoid executing agent-controlled code.
[Environment restrictions](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments),
[Workflow permissions](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository)

A separate App identity and private key per project avoids sharing one credential
across independently administered projects. Anyone able to replace the broker,
registry, or environment restrictions belongs to the trusted administrative
boundary. Agents must use credentials without those privileges.

## Broker and atomic transitions

The broker runs from trusted default-branch code on issue creation or editing,
with a scheduled sweeper and manual recovery trigger. GitHub documents that
issue-triggered workflows use the default branch and require the workflow file
there. [Workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)

Each run reconciles the durable request inbox rather than assuming that one
workflow run corresponds to one request. Workflow concurrency uses a common
group local to the project repository with `cancel-in-progress: false`. Pending runs can still be replaced under
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

Task and queue revisions fence human edits as claim IDs fence agent operations.
An edit or reorder includes the revision the user observed. Stale requests fail
without overwriting newer work, and the viewer preserves the unsaved draft.
Material edits to active criteria or dependencies require explicit release and
claim invalidation. Cancellation invalidates a lease but does not satisfy its
dependents. Evidence stays bound to the completed task revision; a new objective
requires a new task. Reordering does not preempt current claims.

## Standard-work generation

The broker also reconciles default-branch pushes, merged PRs, and verified task
completion against protected `standard-work.json` rules and durable cursors.
It creates ordinary visible tasks; agents, not the privileged broker, perform
mathematical reasoning. The mathematics profile includes inspecting new results
for weaker assumptions, broader statements, reusable lemmas, and limitations.
Reviews commit an artifact with theorem/source references, assumptions, checks,
and clear distinctions among proof, conjecture, counterexample, and intuition.
No useful generalization is an acceptable reasoned outcome.

Rules specify path filters, skill and template versions, priority, evidence, and
generation limits. New tasks retain source SHAs and rule/configuration provenance.
Normalize a PR merge and its push to one source identity; atomically commit the
generation receipt, cursor, and new task. Ignore state, coordination, hints, and
review-only changes by default. Bound depth and task counts, surface deferred
work, preserve cancelled-task receipts, and require explicit bounded backfills.
These controls prevent retries and review reports from producing endless work.

Generated tasks use the same revision-safe editing and proof contracts as manual
tasks. Schema checks can establish that a structured review artifact exists;
formalization or independent review is needed for stronger mathematical evidence.
See [standard-work requirements](deliverables.md#standard-work-generated-by-the-broker).

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

The protected broker App token writes state in its project repository. Evidence
is read from the same repository; no cross-repository proof token is required.
Keep credentials in restricted environment secrets and local credential storage,
never in tasks or hints. Ordinary CI does not receive the broker credential.

## Dashboard, installation, and recovery

GitHub Actions builds and deploys a static Pages shell. The browser fetches the
indexes of selected project repositories using GitHub's API. A private access
token remains in the browser
session and is not embedded in the deployment. Render task and Discussion text
as untrusted content. Pages hosts static HTML, CSS, and JavaScript; runtime state
comes from GitHub. [GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)

The viewer submits human add/edit/prioritize/cancel requests to each project's
Issue inbox and shows pending receipts, accepted changes, errors, and conflicts.
It does not write state directly or receive the broker credential. Generated
tasks expose provenance and can be dismissed; generation-rule changes remain
protected configuration edits.

Installing into a target checkout preserves existing `AGENTS.md` rules and
updates only Hivemind's marked section. Committed `.hivemind/` configuration
identifies the coordinating target repository and project; committed hints preserve findings and handoffs
alongside the code. Installation does not implicitly grant repository access.

The planned standalone uv tool bundles Typer commands, viewer assets, a skill
catalog, and versioned `AGENTS.md`/`SKILL.md` templates. Setup is repeatable;
upgrades preserve customized instructions through managed hashes and reviewable
diffs. Existing repositories receive protected-file changes through setup PRs.
`doctor` verifies live repository permissions and reports remaining manual steps,
not success based only on generated files. See the
[setup and CLI requirements](deliverables.md#setup-and-agent-cli).

History supports inspection and recovery, but a blind reset can resurrect old
claims and erase replay receipts. Repair state through an explicit validated
administrative transition, preserving audit history and invalidating affected
claims. Rebuilding the dashboard index is safe because it is derived from
authoritative state.
