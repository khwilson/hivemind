# Standalone CLI

The first implementation provides repository initialization, packaged AGENTS and
SKILL templates, reviewed agent registration, setup plans and GitHub settings
application, diagnostics, queue requests, and deterministic mathematics inspection
work. The static viewer's GitHub adapter and editing interface remain future work;
the old local-server CLI and database service have been removed.

## Install

Install the versioned standalone tool without checking out the Hivemind project:

```sh
uv tool install 'git+https://github.com/khwilson/hivemind.git@v0.1.0'
hivemind --help
```

Or run it on demand:

```sh
uvx --from 'git+https://github.com/khwilson/hivemind.git@v0.1.0' hivemind --help
```

For development, `uv tool install --editable .` or `uv run hivemind --help` works.
The package needs Python 3.11 or newer and bundles its templates; initialization
does not depend on the developer's checkout. GitHub access uses `GH_TOKEN`, then
`GITHUB_TOKEN`, then an existing GitHub CLI authentication session. It never
prints the credential. Local initialization and setup planning need no network.
[uv tools](https://docs.astral.sh/uv/guides/tools/)

## Prepare a project

Use your actual GitHub account ID, trusted CI check name and issuing App ID, and
trusted code-owner username. `hivemind whoami` reports your account ID. For GitHub
Actions checks, inspect the repository's check-run API response to establish the
issuer instead of assuming that a matching name is sufficient.

```sh
hivemind --path /path/to/target init \
  --repo OWNER/REPO \
  --maintainer-id YOUR_GITHUB_ID \
  --required-check 'quality:TRUSTED_APP_ID' \
  --code-owner TRUSTED_GITHUB_USERNAME \
  --profile mathematics
hivemind --path /path/to/target doctor --local
```

Replace uppercase placeholders before running these commands. `--project` is a
global option if the default repository-derived ID is unsuitable. Specify
`--default-branch` for repositories not using `main`. A different broker release
can be selected with `--source` and an explicit git URL ref; production installs
should pin a commit SHA. `--dry-run` reports proposed files without writing them.

The installer preserves existing AGENTS rules and leaves customized managed
files untouched, reporting conflicts with exit status 1. An existing CODEOWNERS
file is preserved; manually merge the proposed coordinator protection patterns
before setup. Rerunning the same installation produces no duplicate templates.
The general profile installs the skills but leaves the mathematics rule disabled.

Review and commit the generated files through the repository's ordinary process.
Do not include any private key. Upgrades use `hivemind --path PATH upgrade` and
report customized files instead of overwriting them. Registration and revocation
change the protected local configuration; they take effect after reviewed merge.

## Initial GitHub setup

Register a broker App dedicated to this project and install it only in the target
repository. Grant contents and Issues write, checks and pull requests read, and
ordinary metadata read. Give it no administration or workflow-editing permission.
App registration and private-key custody remain manual initial setup.

```sh
hivemind --path /path/to/target setup --app-id APP_ID
hivemind --path /path/to/target setup \
  --app-id APP_ID --client-id APP_CLIENT_ID --apply
```

The first command prints the concrete rulesets and environment policy. `--apply`
uses a maintainer's administrator credential to bootstrap the orphan state
branch, apply separate access and history rulesets, require reviewed default-
branch changes, and restrict the `coordination` environment to the actual default
branch. It also sets the App client ID environment variable. Existing differing
Hivemind rulesets or additional environment branch/tag policies require explicit
reconciliation; setup will not silently replace them. GitHub may require a paid
plan for these controls on private repositories. API failures can leave a partial
installation; inspect the error and rerun setup after resolving it.
[Ruleset API](https://docs.github.com/en/rest/repos/rules),
[Environment policies](https://docs.github.com/en/rest/deployments/branch-policies)

Set `HIVEMIND_APP_PRIVATE_KEY` **in the coordination environment**, using GitHub
settings or secure GitHub CLI input:

```sh
gh secret set HIVEMIND_APP_PRIVATE_KEY --repo OWNER/REPO \
  --env coordination < /secure/path/broker-private-key.pem
hivemind --path /path/to/target doctor --app-id APP_ID
```

The default branch's trusted CODEOWNERS must cover the registry, standard-work
rules, broker workflow, its dependencies, and CODEOWNERS itself. Agent accounts
cannot be trusted owners or administrators. Default-branch review remains human
controlled; accepting task evidence remains automatic. There must be a trusted
reviewer able to approve coordinator changes, including when its author cannot
approve their own PR.

`doctor` checks local assets and live rulesets, state, environment restrictions,
and credential presence. It does not read the secret value, prove correct owner
coverage, or demonstrate that a credential has never leaked. Before deployment,
use a disposable repository to confirm agents cannot push state, delete history,
obtain the broker credential on work branches, or change the registry without
review, and that the broker can accept requests. No such live installation or
negative-access smoke test has been performed by this development run.

## Agent work and queue editing

Generate each agent's private signing key outside its checkout, keep it local,
and register only the public key with a maintainer:

```sh
hivemind keygen --out /secure/path/agent.pem
hivemind --path /path/to/target agent register \
  --name mathematical-worker --github-id AGENT_GITHUB_ID \
  --public-key BASE64_PUBLIC_KEY
```

Review and merge registration. Run agents with ordinary GitHub code/Issue access,
without administrator rights or the broker private key:

```sh
export HIVEMIND_REPO=OWNER/REPO
export HIVEMIND_PROJECT=PROJECT_ID
export HIVEMIND_KEY=/secure/path/agent.pem
hivemind --wait 300 claim
hivemind request show REQUEST_ID
hivemind heartbeat TASK_ID --claim-id CLAIM_ID
hivemind hint TASK_ID --text 'Findings, paths, checks, and unresolved questions'
hivemind submit TASK_ID --claim-id CLAIM_ID --commit FULL_SHA \
  --pr PR_NUMBER --summary 'Evidence for each acceptance criterion'
```

A claim or renewal is effective only after its accepted receipt. Default CLI
requests return immediately as pending; `--wait` optionally waits for a receipt.
A timeout never grants ownership. Use `request show` to retrieve the eventual
outcome. Claims last two hours; renew comfortably before expiry. `release` also
requires the current claim ID. Failed proof verification leaves the claim active
for correction and retry. Completion does not merge the PR.

Humans in the registry can add, edit, cancel, prioritize, and annotate tasks under
their authenticated GitHub identity. Requests must be new, unedited Issues.
Agents sign their requests and can use only their configured capabilities.
Unset `HIVEMIND_KEY` when acting as a maintainer rather than a registered agent.

```sh
hivemind task add --title 'Generalize the theorem' --criteria 'A precise proof passes CI'
hivemind status
hivemind task edit TASK_ID --revision TASK_REVISION --criteria 'Revised criteria'
hivemind task prioritize TASK_B TASK_A --revision QUEUE_REVISION
hivemind task cancel TASK_ID --revision TASK_REVISION
```

Ordering must include every project task exactly once. Stale task/queue revisions
are rejected. Editing active work requires explicit `--release-claim` and
invalidates ownership; finished tasks are immutable. Cancelling a prerequisite
keeps its dependents blocked until an explicit graph edit resolves them.

## Mathematics standard work

The mathematics profile matches Lean and TeX changes integrated into the default
branch. Customize protected `standard-work.json` for additional mathematical
paths. The broker groups changes since its last integrated SHA into an inspection
task per enabled rule, with source SHA, rule version, skill, and generation ID.
Reports belong in `.hivemind/reviews/TASK.md` and must cite the full source SHA
and contain headings Theorem references, Assumptions, Findings, Validation, and
Follow-ups. The broker verifies that committed structure as well as GitHub checks;
it does not establish mathematical correctness. Review-only and coordination changes
do not trigger another inspection. Material new mathematical proofs may trigger
another review. The broker executes no mathematics or agent model itself.

The first state initialization establishes a baseline without historical backfill.
Generation receipts and the cursor commit with tasks, so retries and sweeps do not
duplicate them. This initial implementation reconciles integrated push batches,
not separate pre-merge PR or completion-event rules. There is one generated task
per matching rule per batch, at most 20 configured rules. The profile's per-rule
cap cannot be exceeded because it creates only one task per rule. Explicit
backfill and deeper recursion controls are future work. Batches reaching GitHub's
300-file diff limit fail visibly without advancing the cursor.

## Deployment and implementation limits

Generated broker workflows run on request Issues, default-branch pushes, manual
invocation, and scheduled recovery. Actions installs the pinned standalone CLI,
mints a repository-scoped App token from the restricted environment, reconciles
requests, and verifies required GitHub proof. Live configuration is reread and
checked before committing so old queued runs do not silently use stale policy.
Subsequent deployments use reviewed template updates and GitHub Actions.

The first implementation stores a canonical `state.json` plus inspectable task,
claim, proof, ordering, receipt, and viewer-index files in one atomic commit.
This differs from the eventual partitioned-authority layout in the design. The
contents API's file-size limit bounds this prototype; larger queues need the
partitioned reader before scaling. The viewer source is preserved as a draft,
and its static GitHub editing adapter, Pages deployment, conversation watcher,
and optional FastAPI fanout have not yet been implemented.

The repository's quality workflow runs pytest, Ruff, ty, and package builds.
FastAPI and Uvicorn are optional `relay` dependencies for future fanout; the
standalone CLI does not launch a server or require a database.
