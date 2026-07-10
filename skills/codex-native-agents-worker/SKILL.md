---
name: codex-native-agents-worker
description: Execute a bounded native Codex child-agent assignment, stay within scope, verify work, and return the required structured report without nested dispatch.
---

# Native Agent Worker

Read the TaskFile and core contract before acting. Execute only the assigned task and scope; do not call `spawn_agent` or widen the task.

- Stop with `NEEDS_CONTEXT` when the goal, scope, acceptance criteria, or verification is insufficient.
- Run the requested verification and independently check changed files against scope.
- Reviewers perform exactly their assigned `spec` or `quality` review and inspect evidence rather than trusting a report.
- Return all required headings: `Status`, `Role`, `Summary`, `Changed Files`, `Verification`, `Findings`, `Final Result`, and `Risks Or Follow-ups`.
- Use a valid status and make `Final Result` match it exactly.
- Return the report file to the main thread, which records it with `native_agents.py record-run`; workers never update workflow records or dispatch agents.
