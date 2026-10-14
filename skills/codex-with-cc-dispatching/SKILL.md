---
name: codex-with-cc-dispatching
description: Dispatch end-to-end Claude Code or native Codex workers with pinned routing, exact scope and host provenance.
---

# Codex with CC Dispatching

Read `../codex-with-cc/references/astra-workflows.md` for prepared routes and
`../codex-with-cc/references/lifecycle.md` for actual host lifecycle support.

Configure defaults and MaxParallel from available host capacity. Prepare coherent
end-to-end assignments with explicit reads/writes and dependencies. For a chosen
ready task, prefer `prepare-task -Admit`; it preserves locked admission and slot
reservation. Use `ready-tasks` and separate `admit-task` when queue/dependencies
justify them. Preserve the returned model, effort, task_name, WorkflowPlan and
fork_turns payload.
Simple known-location low-risk work may stay in main without a workflow.
Delegated coupled work needs one end-to-end worker rather than sequential handoffs.

For supported Claude work prefer `claude-process`: prepare exact commands with
`AllowedCommandsFile` and a bounded `ExecutionTimeoutSeconds`, then main invokes
the literal no-argument fixed launcher in its admitted directory. Runtime validates
the immutable plan, main-host identity, provider and command pins. It launches an
external Claude process with no Codex carrier model, child marker or agent ID.
Use process-exit evidence and preserve the user's provider choice.

For child routes, spawn chosen independent tasks before waiting and record returned IDs immediately.
Use host-supported waits across active children; process completed cards and admit
newly ready work without waiting for unrelated children. Main handles requirement
and acceptance decisions while workers explore, implement, test and repair.
Uncertain spawn results retain their reservation until original evidence resolves it.

Preserve current Claude provider selection. A legacy `claude-code` carrier invokes the no-argument
fixed launcher in its prepared directory and relays the compact outcome and evidence
pointers. It does not explore the repo, plan implementation or duplicate the worker's
reasoning. Native children execute directly only when user routing permits, and
return an original report. Prefer `record-native-run -Settle` for native
terminal-evidence workflows; strict-close still needs the actual host close flow. Never switch to native just to
claim speed or let a carrier substitute its own implementation for Claude.

Model, effort and budget changes require a fresh plan. Failures return to a worker
for bounded diagnosis/repair; main decides replanning after repeated failures.
Runtime-supported Claude session continuity may reuse worker context safely; it
never permits reusing a settled Codex host attempt. Each attempt has a fresh
descriptor, preserved original settings and real provenance; child routes also need
a fresh child. Process attempts retain actual PID/start/exit receipts.

For child routes, settle every attempt by real closure or verified terminal evidence when closure is
unavailable. Interrupt is not closure. Cancel unnecessary undispatched plans
formally. Read `review-packet` as an advisory summary, following relevant original
evidence as needed. Standard uses focused main acceptance and current executed checks;
strict additionally requires its independent reviewer/final tasks.

Read `../codex-with-cc/CODEX_WITH_CC.md` only when maintaining legacy descriptors
or supported Claude session modes.
