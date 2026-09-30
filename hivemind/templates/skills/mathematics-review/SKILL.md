---
name: mathematics-review
description: Inspect pushed mathematical changes for proof gaps, assumptions, and reusable results.
---

# Mathematics Review

Read the source SHA and changed theorem references from the task provenance.
Separate the stated result from what the proof or formal checker establishes.
Trace hypotheses, boundary cases, cited lemmas, and any implicit assumptions.
Record the exact checks performed and distinguish unverified steps from failures.

Commit a review in .hivemind/reviews/TASK.md with source SHA, theorem references,
assumptions, findings, validation, and follow-ups. Link evidence and counterexamples.
Create actionable tasks for gaps or reusable lemmas; do not assert that formatting
checks or successful CI establish the truth of unformalized mathematics.
A review with no identified gap is valid if it explains the inspected scope.

Use Markdown headings exactly `Theorem references`, `Assumptions`, `Findings`,
`Validation`, and `Follow-ups`, and cite the full source SHA from task provenance.
The broker checks this structure; it does not establish mathematical correctness.
