---
name: handoff-and-followups
description: Leave committed Hivemind handoffs and create scoped actionable follow-up tasks.
---

# Handoff And Followups

Use `hivemind hint TASK --text ...` to record findings, affected paths, useful
commands, failed approaches, and unresolved questions. Commit the hint alongside
the work and link its conversation. Keep credentials and private-key material out.

Add follow-ups with `hivemind task add --title ... --criteria ...` and explicit
dependencies. Check existing tasks first. A child cannot depend on its parent;
if an active parent needs children, release it before claiming a child. Keep
mathematical conjecture, proof, formalization, and documentation tasks distinct
when they have independently assessable deliverables.
