---
name: codex-native-agents
description: Optimize authorized development work by choosing main-thread execution or bounded native Astra subagents according to task independence, complexity, risk and parallelism; use for explicit delegation and substantial development tasks that benefit from coordination.
---

# Codex Native Agents

The main thread owns dispatch, architecture, scope, acceptance, and delivery.
Within an authorized development task, the main thread may choose native
subagents without asking for delegation permission again. This skill authorizes
that implementation choice only; preserve explicit user limits and host policy.
Workers cannot call `spawn_agent` recursively or expand the assignment.

## Decide before creating artifacts

- Keep small fixes, uncertain design choices, tightly coupled edits and short
  investigations in main. Complexity alone does not justify delegation.
- Delegate a bounded task when an independent worker can make progress while
  main does useful work and the expected benefit exceeds dispatch/review cost.
- Parallelize independent tasks only after mapping dependencies and all files
  they may read/write. Multiple readers may share scope. A writer conflicts
  with readers and writers in its scope. Serialize shared indexes, lockfiles,
  generated catalogs and integration changes under one owner.
- Default to standard acceptance: main reviews the actual diff and executes
  relevant checks. Choose strict before dispatch for high-risk changes or
  explicitly requested independent reviews. Do not downgrade a running workflow.
- Use Astra low for simple investigation, medium for ordinary work, high for
  complex work/review, xhigh for the hardest judgement and final verification.
  If the advertised route is unavailable, keep work in main or explicitly replan;
  do not silently switch to another model. One failed attempt may escalate one
  profile with a fresh preparation. After the second attempt return to main.

Explain the split briefly, then act. An ordinary task requires no workflow when
main can finish it directly. Do not treat a mention of agents as a dispatch order.

When delegating, read [CODEX_NATIVE_AGENTS.md](CODEX_NATIVE_AGENTS.md) and
[the command guide](references/adaptive-workflows.md). Read stage skills only
for the current stage. `contract.json` supplies model/role defaults.

## Native task envelope

```text
[NATIVE_CODEX_AGENT_TASK]
WorkflowId: native-auth-workflow
TaskId: auth-token-implementation
Role: implementer
TaskFile: .codex/codex_native_agents/tasks/auth-token-implementation.md
Scope: src/auth,tests/auth
ModelProfile: balanced
Writable: true
Parallel: false
DispatcherRole: main
[/NATIVE_CODEX_AGENT_TASK]
```

Use `prepare-spawn` to generate the envelope and host-compatible payload.
Retain `fork_turns: "none"` or legacy `fork_context: false`, model and effort.
Spawn the ready wave before waiting. While it runs, main stays in its reserved
scope; consume whichever result completes first and recompute readiness.

## Evidence boundary

Original local transcripts verify child identity, terminal state, final report,
model and effort. Missing evidence is a blocker, not permission to invent it.
Without close_agent, record terminal evidence and closeStatus=unsupported.
Child-session provenance and host tool isolation help prevent nested dispatch;
they do not authenticate a hostile process with the same local file privileges.
Whole-workflow acceptance belongs to main. Final-verifier workers call
`verify-final-inputs`, never their own whole-workflow acceptance.
