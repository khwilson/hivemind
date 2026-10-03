# Hivemind backlog

These are requested features, not implemented behavior.

## Reviewer bots

Add a reviewer bot type that reviews PRs and submits GitHub approvals when they
meet repository-defined standards. Keep those standards in protected
configuration and record the reviewed head SHA, checks, findings, and approval
rationale. Re-review when the PR head changes. Reviewers must not approve their
own work or bypass branch rules; approval and merging remain separate actions.
Define permissions, failure handling, and human escalation before deployment.
