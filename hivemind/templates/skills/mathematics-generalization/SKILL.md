---
name: mathematics-generalization
description: Explore generalizations of mathematical results and distinguish conjectures from proofs.
---

# Mathematics Generalization

Inspect the source commit and theorem statements identified by the task.
Consider weakening hypotheses, extending parameter ranges, abstracting structures,
extracting reusable lemmas, or transferring the argument to related settings.
Use the proof's actual dependencies to guide the search, and test boundary cases
or counterexamples before suggesting a stronger claim.

Commit .hivemind/reviews/TASK.md with source SHA, theorem references, assumptions,
findings, validation, and follow-ups. Label each extension proved, conjectural,
unchecked, or ruled out, with its supporting reasoning. A justified finding
that no useful extension was found satisfies an inspection task. Do not invent
a generalization to fill a quota. Create separate follow-up tasks for concrete
proof or formalization work rather than expanding the current assignment.

Use Markdown headings exactly `Theorem references`, `Assumptions`, `Findings`,
`Validation`, and `Follow-ups`, and cite the full source SHA from task provenance.
The broker checks this structure; it does not establish mathematical correctness.
