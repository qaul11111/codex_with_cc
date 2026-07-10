# Codex Native Agents

This is the portable contract for the native Codex agent workflow. Read it
before dispatching a child agent. `contract.json` is the machine-readable source
for all shared tokens and policy values.

## Core Contract

1. The main thread owns dispatch, design, task boundaries, review decisions,
   acceptance, and final delivery.
2. Workers are context consumers. They cannot call `spawn_agent` recursively,
   broaden scope, or dispatch additional workers.
3. Every delegated task has one `WorkflowId`, one stable `TaskId`, a TaskFile,
   and a native task envelope.
4. The main thread dispatches native child agents with `fork_context: false`.
5. The configured model profile is soft policy. An unavailable model falls back
   to parent inheritance and is recorded in the workflow artifact.
6. Writable tasks may run in parallel only with explicit, non-overlapping scope.
7. Failed or blocked work may escalate one model tier at most once; repeated
   failure returns control to the main thread.

## Native Task Envelope

Every child prompt contains this envelope:

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

## TaskFile Contract

Each TaskFile includes these non-empty sections:

- `Goal`
- `Allowed Scope`
- `Forbidden Actions`
- `Acceptance Criteria`
- `Verification`
- `Report Requirements`

## Roles And Review Gates

Worker roles are `planner`, `implementer`, `researcher`, `reviewer`, and
`final-verifier`. Implementer work is accepted only after `spec` review,
`quality` review, and final verification.

## Worker Reports

Every worker report contains these headings:

```text
Status
Role
Summary
Changed Files
Verification
Findings
Final Result
Risks Or Follow-ups
```

`Status` and `Final Result` must match and use one of `DONE`,
`DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, `BLOCKED`, or `FAIL`. Verification lists
the commands actually run and their outcomes.
