# Worker permissions

These permissions cover the implemented CLI and a worker contributing code in
the target repository. GitHub credentials and Hivemind signing keys are separate:
both are needed to claim work. Provider authentication for Codex or Claude is a
third, independent credential. See [worker startup](agents.md).

## GitHub access

Use a dedicated worker account. For branches in the target repository, give it
the **Write** repository role in an organization, or ordinary collaborator access
in a personal repository. Do not make it an administrator, coordinator CODEOWNER,
or ruleset bypass actor. A token cannot exceed its user's repository access.

For a supported fine-grained PAT or GitHub App user access token, select only the
target repository and grant:

| Repository permission | Queue operations only | Complete code contribution loop | Purpose |
| --- | --- | --- | --- |
| Metadata | Read | Read | Repository metadata; included automatically |
| Contents | Read | Read and write | Read config, queue and receipts; clone and push work branches and committed hints |
| Issues | Read and write | Read and write | Open signed request Issues for claims, heartbeats, releases, submissions, new tasks and notes |
| Pull requests | None | Read and write | Open and update the work PR |

Write includes read. The queue client reads `index.json` and
`receipts/<request-id>.json` through the Contents API and posts envelopes through
the Issues API. It does not directly write the state branch or verify completion
checks. These requirements follow GitHub's [Contents API](https://docs.github.com/en/rest/repos/contents#get-repository-content),
[Issues API](https://docs.github.com/en/rest/issues/issues#create-an-issue), and
[pull request API](https://docs.github.com/en/rest/pulls/pulls#create-a-pull-request).

Optional permissions depend on the worker's tools:

| Repository permission | Level | When needed |
| --- | --- | --- |
| Actions | Read | Inspect private workflow runs and logs |
| Checks | Read | Inspect private check runs with a compatible token |
| Commit statuses | Read | Inspect private commit statuses |
| Discussions | Read and write | Create discussions or replies through GitHub's API when Discussions is enabled |

These are not required by the Hivemind queue commands. Completion is verified by
the broker using its own credential. Workers do not need Actions write, Checks
write, Commit statuses write, Administration, Secrets, or Workflows write.
Workflow-file changes require separately reviewed permission; the ordinary
worker profile does not include it.

### Token compatibility

GitHub currently documents limitations for fine-grained PATs used by outside or
repository collaborators, and for the Checks API. In particular, a separate
worker collaborating on a personal repository such as `khwilson/hivemind` should
not assume a fine-grained PAT works. Use a compatible user credential, such as a
classic PAT with `public_repo` for public repository work, or `repo` for private
repository work, subject to organization policy. These classic scopes are
broader than the table above and cannot select just one repository; limit the
worker account's repository access accordingly. See GitHub's [PAT limitations
and scopes](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).

Hivemind resolves `GH_TOKEN`, then `GITHUB_TOKEN`, then `gh auth token`. Run
`hivemind whoami` and verify that its numeric GitHub ID matches the registered
worker. Use a user credential for this flow: a broker App installation token is
not a substitute for the worker's user identity. Configure Git push authentication
for the same account, for example with `gh auth setup-git`; SSH pushes may use a
different account from API calls unless configured deliberately.

## Hivemind authorization

A maintainer must merge the worker registration into protected `hivemind.toml`:

- The Ed25519 public key and its matching fingerprint ID.
- The numeric GitHub ID of the account opening request Issues.
- The allowed project IDs in `projects`.
- The permitted actions in `actions`, with `revoked = false`.

Registration defaults to `claim`, `heartbeat`, `release`, `submit`, `add`, and
`note`. It does not grant `edit`, `prioritize`, or `cancel`; those require explicit
authorization. Unsigned human queue edits require a configured maintainer GitHub
ID and verified request provenance. They cannot claim or submit agent work.
Keep the private signing key outside the repository with mode `0600`.

Neither a GitHub token nor a registered signing key alone grants a claim. The
broker checks the Issue author's GitHub ID, signature, project and action scope,
revocation, and request validity. A worker owns a task only after an accepted
claim receipt; subsequent operations must respect the claim fence and lease.

## Protected branches and broker permissions

### Private repositories

The CLI and broker use authenticated GitHub APIs and support private repository
access. Install the broker App on the private target and grant worker credentials
access to it. The required rulesets and environment branch restrictions need
GitHub Pro for personal repositories, or GitHub Team/Enterprise for organization
repositories; GitHub Free is insufficient for this protected private setup.
See GitHub's [ruleset availability](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)
and [environment availability](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).

The GitHub-backed viewer is still planned. It must fetch private queue state
using each viewer's authorized credential, rather than bundle that state or a
credential into public Pages assets. A private source repository does not by
itself make a Pages website private. Private broker operation must be verified
in a live smoke test before declaring a deployment ready.

### Branch controls

Worker pushes belong on ordinary work branches. The configured branch rules must
protect the default branch's coordinator configuration and allow only the
dedicated broker App to update `hivemind-state`. Repository Write and PR write
are broad GitHub permissions: the table alone does not enforce these boundaries
or prohibit merges. Apply and inspect the rules using maintainer credentials;
workers must follow the PR process and must not bypass it.

The separate broker App needs Contents write, Issues write, Pull requests read,
Checks read, Commit statuses read, and Metadata read. Commit statuses read is
needed for [combined status verification](https://docs.github.com/en/rest/commits/statuses#get-the-combined-status-for-a-specific-reference).
Its private key stays in the restricted Actions environment. Never provide it
to a worker. Initial `setup --apply` uses a maintainer administrator credential;
`doctor` checks requiring administrative visibility are also maintainer
operations, not requirements for ordinary workers.

This is the permission contract derived from the current code and GitHub API
documentation, not a claim that a live worker/broker deployment has been tested.
