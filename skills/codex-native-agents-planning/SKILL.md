---
name: codex-native-agents-planning
description: Plan bounded native Codex child-agent workflows with roles, disjoint scopes, acceptance criteria, and review gates before dispatch.
---

# Native Agent Planning

Read `../codex-native-agents/CODEX_NATIVE_AGENTS.md`. Use this for a request that benefits from delegation.

- Give the request one `WorkflowId` and every assignment a stable `TaskId`.
- Choose one contract role, model profile, writable state, dependencies, and project-relative scope per task.
- Write every TaskFile with the six required sections from the core contract.
- Parallel writable tasks must have explicitly non-overlapping scopes; otherwise serialize them.
- Plan `spec`, `quality`, and `final-verifier` gates for each implementer.
- Keep architecture, task boundaries, acceptance, and rework decisions with the main thread.
- Return `NEEDS_CONTEXT` instead of dispatching an assignment with unresolved decisions.
