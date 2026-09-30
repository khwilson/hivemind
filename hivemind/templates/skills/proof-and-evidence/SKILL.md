---
name: proof-and-evidence
description: Prepare exact GitHub proof and committed review evidence for a Hivemind completion request.
---

# Proof And Evidence

Run the repository's required checks and identify the current PR head SHA.
Commit the deliverable and useful hints; submit a full SHA, PR number, claim ID,
and explanation of each acceptance criterion. Do not substitute a different
commit's successful checks. The broker verifies required check names and issuers.

For mathematics inspections, include a .hivemind/reviews/TASK.md report with
source SHA, theorem references, assumptions, findings, validation, and follow-ups.
Prose and structural validation do not replace mathematical proof. Report that
limit clearly. Completing work does not merge its PR; obey the project's
integration policy before depending on unmerged changes.

Use Markdown headings exactly `Theorem references`, `Assumptions`, `Findings`,
`Validation`, and `Follow-ups`, and cite the full source SHA from task provenance.
The broker checks this structure; it does not establish mathematical correctness.
