---
name: codex-native-agents
description: Use for explicit child-agent, subagent, child-thread, delegation, worker-execution, or multi-agent requests; route bounded work through native Codex agents and the codex_native_agents_workflow contract.
---

# Codex Native Agents

## Core Rule

Use this skill for explicit delegation work. The main thread owns dispatch,
architecture, task boundaries, review decisions, acceptance, and final delivery.
Workers are context consumers and cannot call `spawn_agent` recursively.

Read `CODEX_NATIVE_AGENTS.md` and `contract.json` before dispatching work.
The contract is the shared source for roles, model profiles, task files, reports,
review gates, and delegation triggers.

## Native Dispatch

The main thread creates a bounded TaskFile, chooses the contract model profile,
and calls native `spawn_agent` with `fork_context: false`. A configured model is
soft policy: if it is unavailable, inherit the parent model and record the
fallback. Run writable tasks in parallel only when their declared scopes do not
overlap.

Every child prompt must include this task envelope:

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

Child agents read only their assigned TaskFile, stay inside its scope, complete
the requested verification, and return the required structured report. The main
thread uses native agent lifecycle tools to review, request bounded rework, and
close completed agents.

## Gate Provenance Boundary

The hook rejects `spawn_agent` when a host-provided transcript's first
`session_meta` record explicitly identifies a child session through
`source.subagent`, `thread_source: subagent`, or `parent_thread_id`; it also
rejects corresponding top-level hook-input signals. Codex 0.144 exposes
`transcript_path`, with `transcriptPath` accepted for compatibility.

This is defense in depth, not a hard identity proof. A host can omit the
transcript path or make it unreadable, so a compliant dispatch is not rejected
solely for absent provenance. In that case the workflow depends on host tool isolation
to prevent workers from accessing `spawn_agent`.

## Acceptance

Implementer work requires accepted `spec` review, `quality` review, and a
`final-verifier` before workflow acceptance. Every worker report must include
the contract headings and use the same valid token for `Status` and
`Final Result`.
