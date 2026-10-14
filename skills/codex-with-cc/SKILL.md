---
name: codex-with-cc
description: Coordinate Claude Code or native Codex delegation with a clean main context. Main plans and reviews; end-to-end workers explore, implement, test and repair within explicit scope.
---

# Codex with CC

For authorized development using this workflow, keep main focused on requirements,
decisions, task boundaries and final acceptance. Workers own substantial repository
exploration, implementation, test execution and local repair. Main may directly finish simple,
known-location, low-risk small tasks. Ambiguous, exploration-heavy or substantial
coupled work goes to one end-to-end worker; parallelize larger independent scopes
when useful. Do not move substantial work back to main to claim speed. Discussion
alone never starts workers, and explicit user routing and permission boundaries prevail.

Read [references/astra-workflows.md](references/astra-workflows.md) for commands and
[references/lifecycle.md](references/lifecycle.md) for the selected route before dispatch. Read
[CODEX_WITH_CC.md](CODEX_WITH_CC.md) only for legacy runners or session diagnostics.
Load sibling skills only for needed detail.

## Main-owned decisions

- Main resolves product ambiguity, chooses scope, backend, model, effort and acceptance
  depth. Workers make routine implementation choices inside those boundaries.
- Preserve the user's current Claude provider choice. For Claude work, prefer
  supported `claude-process`: the fixed launcher runs Claude without a Codex model
  carrier. Use legacy `claude-code` when needed, or native only when routing permits.
  Never silently replace Claude to claim speed. Workflow defaults can be overridden per task with a decision reason;
  verify support and preserve each attempt's original settings.
- Prefer `standard` with focused main review and relevant executed checks. Add a
  targeted independent reviewer when useful. Select `strict` for required or justified
  independent spec/quality/final review; it is not mandatory for ordinary changes.
- Configure `MaxParallel` from actual host capacity. For a chosen ready task, use
  `prepare-task -Admit` to prepare and admit in one call. Use `ready-tasks` and
  separate `admit-task` only when queue/dependencies justify them; `advise-task`
  is optional decision support. Queued preparation is not dispatch. While workers
  execute, main handles decisions, dependencies and acceptance.
  Delegated failures return to a worker for diagnosis/repair; main replans repeated failures.

## Compact work and results

Each TaskFile retains Goal, Allowed Scope, Forbidden Actions, Acceptance Criteria,
Verification and Report Requirements. A few precise lines per section are sufficient.
Do not micro-delegate files or impose discovery → implementation → testing handoffs.
One worker should explore, change, check and repair a coherent assignment.

Worker reports contain Status, Role, Summary, Changed Files, Verification, Findings,
Final Result and Risks Or Follow-ups. Return a brief result card with changed paths,
check outcomes, risks and evidence links; keep full logs and detailed reports in
artifacts. Main reads the card first, follows relevant evidence, and pulls targeted
diffs where needed for an informed decision. Avoid relaying whole reports or redoing
worker exploration. Formatting variations are accepted; missing/duplicate fields
and inconsistent Status/Final Result are rejected. Preserve the original report.

## Execution and acceptance

For `claude-process`, main prepares exact task-specific commands and a bounded
timeout, then invokes the literal no-argument fixed launcher in the prepared
directory. Runtime checks the immutable plan, main-host identity, provider and
command pins. This is a worker process, not a Codex child; no carrier model runs.
Legacy Claude carriers only launch and relay; native workers execute directly.
For child routes preserve admitted model, effort, task_name, WorkflowPlan and
fork_turns. Never bypass the launcher or mutate global provider configuration.
Claude session reuse is limited to runtime-supported safe continuity; every Codex
host attempt is fresh and settled attempts cannot be reused.

Processes retain PID/start/exit and report evidence under `process-exit`, with
bounded timeout cancellation; never invent agent IDs or thread closure for them.
Record actual returned agent IDs for child routes. For native terminal-evidence workflows, use
`record-native-run -Settle` to import and settle in one call; strict-close requires
the actual host close flow. Use `review-packet` for a bounded advisory result card,
then follow relevant original evidence. Every attempt retains original host
provenance and terminal evidence. Interrupt is not closure. Verified end with no
close interface is “执行已结束；宿主不提供线程关闭接口。”

For `standard`, judge scope and quality from actual changes and relevant evidence,
invoke the deterministic `run-checks` acceptance gate, record `record-main-review`,
then `verify-workflow`. Worker test logs do not automatically substitute for that
gate. Once its evidence is current, rerun only for changed covered inputs/runs,
failed checks or unresolved risk. Main retains final judgment and explicitly
disposes of non-blocking DONE_WITH_CONCERNS findings. Missing verification, FAIL,
BLOCKED and NEEDS_CONTEXT cannot be waived into completion.

Checks cover the whole project by default; scoped evidence requires complete
input/dependency declarations. For `strict`, reviews bind current implementation
runs and the final worker uses `verify-final-inputs`. Main accepts after settlement.
Cancel unnecessary undispatched plans with `cancel-prepared-task`. Use `inspect-runs`
and `workflow-metrics` when needed; missing usage is unknown, estimates are not bills,
and lower elapsed time or cost must be measured rather than promised.
