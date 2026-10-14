# Astra workflow operation

Main owns requirements, task boundaries, routing decisions and focused acceptance.
Simple, known-location, low-risk small tasks may stay in main. Delegate substantial
exploration, implementation, tests and local repair as one end-to-end assignment;
parallelize independent chunks. Coupling is a reason for one worker, not for moving
substantial implementation back to main. Create workflows for authorized worker work. Commands below use the installed
scripts/runtime.py, terminal cwd at the target project and one absolute ArtifactRoot.

## Configure before preparation or dispatch

```sh
python3 <runtime.py> configure-workflow -WorkflowId <id> -ProjectRoot <project> -ArtifactRoot <artifacts> -Profile standard -MaxParallel <available-host-slots>
```

Standard is the default for new workflows. Main selects strict when independent
spec/quality/final review is required or warranted. A high-risk label alone is not
a reason to launch three reviewers without considering what evidence is needed. Missing policy keeps legacy strict rules. Existing workflows with
tasks, runs, prepared tasks or spawns cannot change policy. Create a new WorkflowId
instead; old acceptance records are not migrated.

| Setting | Default | Purpose |
|---|---|---|
| -CarrierModel / -CarrierEffort | gpt-5.6-luna / low | Legacy claude-code launch and relay only |
| -WorkerModel | sonnet | Claude Code alias; check actual provider mapping |
| -NativeModel / -NativeEffort | gpt-6-astra / high | Native child execution |

These are workflow defaults; prepare-task can override models/effort per task with
-DecisionReason. -WorkerEffort selects the actual Claude CLI effort independently
of the carrier. -MaxBudgetUsd caps a Claude attempt through the CLI; it is not a
workflow-wide or cross-provider spending guarantee. Verify provider support.
Preserve the current Claude provider choice. Claude requests prefer `claude-process`
when the local POSIX host supports it: Claude runs as an external worker process,
without a Codex carrier model. `claude-code` remains the legacy child route.
If the user has not required Claude
or provider-specific capabilities, main may choose native to remove the carrier
layer while retaining context isolation. This is a selectable latency optimization,
not a measured speed guarantee. These defaults do not change global settings. Confirm availability in the active
host catalog. If a default is unavailable, configure a supported choice explicitly.
Read lifecycle.md and configure-lifecycle from actual host tools before any spawn.
Native collection requires local Codex JSONL logs with child provenance, terminal
events, model context and a final response. Cloud/opaque-only logs are unsupported.
If the active task still injects old compulsory routing, use a new task after reload.

## Claude process route

Main keeps requirements, boundaries and acceptance. The process performs substantial
exploration, implementation, checks and repair inside the task scope. It is not a
Codex child thread, does not consume a carrier model, and must never receive a
fabricated agent ID or child marker. Small known low-risk work can stay in main.

Configure `process-exit` from an actual active-tool-catalog snapshot containing the
terminal execution tool; it does not require spawn/close tools:

```sh
python3 <runtime.py> configure-lifecycle -WorkflowId <id> -ArtifactRoot <artifacts> -Policy process-exit -HostToolsFile <actual-host-tools.json>
```

Authorize task-specific shell commands using an explicit JSON file. Commands use
exact argv, not wildcard shell permission. Pin local scripts/configuration that
control execution; changing a pinned input needs a fresh plan. For example:

```json
{"schemaVersion":1,"commands":[{"argv":["python3","tools/check.py"],"pinnedFiles":["tools/check.py"]}]}
```

```sh
python3 <runtime.py> prepare-task -WorkflowId <id> -TaskId <task> -ArtifactRoot <artifacts> -Backend claude-process -Role implementer -TaskFile <task.md> -Scope src/module -AllowedCommandsFile <commands.json> -ExecutionTimeoutSeconds 900 -Admit
```

Use the returned launch directory as the terminal tool's working directory and
execute the exact literal `${CODEX_HOME}/bin/codex-with-cc-launch` path with no
arguments (expand the path before dispatch). Do not wrap it or run `claude`
directly. The hook calls `validate-process-launch -LaunchDirectory <directory>`;
the launcher also validates the immutable registered plan, admission, descriptor,
original main identity, provider snapshot and command pins before any model call.
`-BypassPermissions` is rejected for this route. Commands currently require simple
literal arguments; shell wrappers, inline interpreter code, whitespace and globs
are unsupported. No global provider or blanket shell permissions are changed. Unsupported routing
returns to main for an explicit choice; do not silently switch providers.

Each attempt has its own descriptor, command authorization, timeout and evidence;
Claude process session reuse is currently disabled.
The process lifecycle records actual start/PID/exit and original output; timeout
cancellation is bounded and cannot become successful completion from report text.
`cancel-prepared-task` applies only before launch; it is not a running-process kill
command. Verify process evidence and the normal main acceptance gates after exit.
Keep failed/interrupted attempts and their real status. A successful terminal tool
return alone is not acceptance. Native/legacy thread-close language does not apply.

Command recognition and local evidence are not a sandbox or tamper-proof host
attestation. Exact authorization reduces routine approval prompts; a newly needed
command or changed pin requires main to prepare updated authorization. Runtime
support is local POSIX only. No latency or cost saving is established by this route;
missing usage is unknown and provider estimates are not invoices.

## Native and legacy child routes

For a chosen task ready to dispatch, prefer `prepare-task -Admit` as shown in the
compact path below. Separate preparation is useful for queued dependencies;
`ready-tasks` and `advise-task` are optional, not per-task ritual.

```sh
python3 <runtime.py> prepare-task -WorkflowId <id> -TaskId <task> -ArtifactRoot <artifacts> -Backend claude-code -Role implementer -TaskFile <task.md> -Scope src/module
```

Use codex-native for native execution when user routing permits. TaskFiles retain
the six contract sections, with short outcome-oriented content. Do not fragment a
coherent task into discovery, implementation and test workers merely to fill fields.
Reviewer plans require -ReviewForTaskId, -ReviewForRunId and -ReviewKind.
-AllowParallel requires disjoint writes. -BypassPermissions remains opt-in.
With MaxParallel, preparation queues a pinned plan; admission returns the exact
spawn payload. Without it, historical prepared routing remains supported. Preserve its WorkflowPlan
line, model, reasoning_effort and fork_turns. Record the actual returned agent id
immediately. For Claude Code the carrier invokes the no-argument launcher with cwd
set to the generated descriptor directory. The carrier is a launcher/relay: it does
not explore the repository, replan the task or duplicate worker reasoning. Prepared
launches return compact summaries and preserve original stdout/stderr on disk. Prepared Claude tasks require ArtifactRoot
inside the project, such as .codex/codex_with_cc/claude-delegate. The launcher binds
the actual child in memory after checking original host model/provenance. Legacy
manual launch.json still works. Each attempt needs a fresh prepared descriptor;
unexecuted prepared tasks block acceptance.

An authorized main thread can withdraw an unnecessary, undispatched plan:

```sh
python3 <runtime.py> cancel-prepared-task -PlanFile <plan.json> -Reason "Requirement was withdrawn before this worker was dispatched."
```

The command preserves the original plan and an exact workflow backup, records the
reason, time, acting main-thread identity and hashes in an audit receipt, and marks
the prepared entry cancelled. It rejects existing dispatches, runs, launcher claims
or original host evidence of a child. For ambiguous same-TaskId prior executions,
settle those attempts rather than using cancellation. Repeating the same cancellation
is idempotent; its original reason cannot be overwritten. A cancelled plan cannot be
dispatched or imported. Prepare a fresh plan for later work. `verify-workflow` checks
the receipt and original evidence before excluding a cancelled plan from pending
work; withdrawal never creates a DONE report or makes an empty workflow pass.

Visible spawn plans are checked against pinned metadata. Preserve the returned
task_name as well: encrypted desktop deliveries bind that unique generated handle
to the full registered plan using the original parent's admit-task output
(prepare-task for workflows without adaptive admission),
spawn call/result, and the identical opaque message in the child's NEW_TASK
delivery. The original parent session must be available. Missing, ambiguous or
mismatched evidence is rejected; ciphertext is never decrypted or treated as a
visible WorkflowPlan marker. In-turn MESSAGE coordination cannot supply a new
binding, and a new host turn cannot reuse an earlier turn's dispatch.

After a native child finishes, locate its original host log and import the result:

```sh
python3 <runtime.py> record-native-run -PlanFile <plan.json> -AgentId <actual-id> -TranscriptPath <original.jsonl>
```

This checks child identity, project, model, terminal event and original final report.
Both legacy channel=final and desktop phase=final_answer are supported. Report
headings may be plain, Markdown ATX or bold, with optional colons and inline values. Case, order
and an ordinary introductory sentence are flexible. All eight fields must occur
exactly once outside fenced examples; roles and status agreement remain required. The complete original response is preserved,
not the potentially shortened task_complete.last_agent_message summary. Native
encrypted-dispatch imports pin the relevant parent records and recheck them on
verification; later unrelated parent activity may append normally.
It invokes no model. Settle the lifecycle with record-agent-terminal or actual close
as required. Preserve every earlier attempt and its actual status.

## Fewer coordination calls and compact review

For a task ready to dispatch under an adaptive workflow, combine preparation and
admission. If admission fails, the immutable prepared plan remains queued and can
be admitted later; no spawn payload is issued on failure.

```sh
python3 <runtime.py> prepare-task -WorkflowId <id> -TaskId <task> -ArtifactRoot <artifacts> -Backend codex-native -Role implementer -TaskFile <task.md> -Scope src/module -Admit
```

For native terminal-evidence workflows, combine result import and settlement:

```sh
python3 <runtime.py> record-native-run -PlanFile <plan.json> -AgentId <actual-id> -TranscriptPath <original.jsonl> -Settle
python3 <runtime.py> review-packet -WorkflowId <id> -ArtifactRoot <artifacts>
```

`-Settle` rejects strict-close before import; use actual host closure and its normal
recording flow there. If import succeeds but settlement fails, retain the imported
run and retry `record-agent-terminal` with the same original transcript, not import. Combined calls preserve the same admission, provenance and
terminal-evidence checks. They reduce these four coordination calls to two, not
total elapsed time by half. Separate commands remain useful for queued dependencies
or when dispatch/import and settlement must be handled at different times.

`review-packet` is read-only and deterministic. Its bounded summaries mark truncation
and link original artifacts; missing sections are explicit. `advisoryOnly` and
`acceptanceFreshness` state that the packet is not an acceptance receipt, a freshness
verification or a substitute for code/check review. Main starts with the card's changed
paths, check results, findings/risks and evidence links, then reads targeted diffs
or logs needed to decide. Keep full reports, streams and transcripts on disk.
Prepared Claude launcher output follows the same compact relay principle.

Avoid automatically reading every skill, full repository dump or previous report.
Use exact no-fork prepared payloads and the smallest sufficient task context.
Safe runtime-supported Claude session continuity can reduce repeated worker context;
it never permits reusing a settled Codex host attempt. See CODEX_WITH_CC.md only when
those legacy session modes are relevant. Every fresh attempt still has its own
descriptor, original report and lifecycle evidence; child routes need a fresh child.

## Main-owned routing and ready waves

Use `advise-task -WorkKind development -Complexity complex -Independent -EstimatedMinutes 20 -OverheadMinutes 2`
for optional routing advice. `-WorkKind decision` or `discussion` supports main-owned
work; `development` is the default. Mark `-SmallKnownTask` only when main judges the
task simple, known-location and low-risk. Other coupled or low-parallel-benefit
work is a single-worker candidate; independent worthwhile work can be delegated
in parallel. Estimates are not benchmarks or automatic routing decisions. Main
chooses task size, backend and effort; avoid universal line/file/time thresholds.

Configure `-MaxParallel <available execution capacity>` and optional repeated
`-MainScope <main-write-path>` before preparation. Scopes are literal project
paths, not globs. Each task can declare `-ReadScope <dependency-path>`,
`-DependsOn <registered-task>` and `-AllowParallel`. Scope is writable for
implementers and read-only for other roles; ReadScope adds relevant reads.

```sh
python3 <runtime.py> prepare-task -WorkflowId <id> -TaskId <task> -ArtifactRoot <artifacts> -Backend claude-code -Role implementer -TaskFile <task.md> -Scope src/widget -ReadScope src/shared -WorkerModel <available-model> -WorkerEffort medium -DecisionReason "Bounded implementation with an established test surface" -AllowParallel
python3 <runtime.py> ready-tasks -WorkflowId <id> -ArtifactRoot <artifacts>
python3 <runtime.py> admit-task -PlanFile <returned-plan.json>
```

The ready list is advisory. Admission rechecks dependencies, read/write conflicts,
serial tasks, main reservations and capacity under the workflow lock. It reserves
before launch, so two concurrent admissions cannot consume the same final slot.
A queued plan cannot launch or import a result. Each reservation binds one attempt;
resolve uncertain host spawns rather than redispatching an admitted plan.
Capacity covers this workflow only: account for other workflows, processes and host children
when choosing MaxParallel. Separate workflows sharing writes need main coordination.

Dispatch the chosen ready wave, let main handle decisions and focused acceptance,
and recompute
as attempts settle. Only actual dependencies delay the next task. A dependent plan
pins upstream run IDs at admission; rerunning an upstream task invalidates the
latest dependent result, while older attempts remain valid historical evidence.
DONE_WITH_CONCERNS dependencies need current main review/dispositions and checks.

Per-task `-CarrierModel`, `-CarrierEffort`, `-WorkerModel`, `-WorkerEffort`,
`-NativeModel` and `-NativeEffort` require DecisionReason. They do not change prior
plans or workflow defaults. Explicit host effort overrides are checked against
original turn_context evidence. Unsupported settings return to main for an explicit
new plan; do not silently switch providers or models. Have a worker diagnose and repair a
failure within scope; main chooses an explained fresh attempt or scope change.
Repeated failure should trigger replanning rather than identical redispatches.

## Standard acceptance

Create checks.json under ArtifactRoot with explicit argv arrays:

```json
{"checks":[{"argv":["python3","-m","pytest","-q"],"cwd":".","timeoutSeconds":300}]}
```

```sh
python3 <runtime.py> run-checks -WorkflowId <id> -ArtifactRoot <artifacts> -ChecksFile <checks.json>
python3 <runtime.py> record-main-review -WorkflowId <id> -ArtifactRoot <artifacts> -EvidenceFile <returned-evidence.json> -ReviewFile <review.md>
python3 <runtime.py> verify-workflow -WorkflowId <id> -ArtifactRoot <artifacts>
```

Workers select, execute and repair relevant tests during their assignment. Main
invokes the deterministic run-checks acceptance runner and reviews its evidence;
this does not require importing verbose logs or repeating worker reasoning. Ordinary
worker test logs are not automatically imported as acceptance-gate evidence. Once
required checks pass with valid current bindings, do not repeat them without changed
covered inputs/runs, a failure or unresolved risk. No automatic test-cache reuse is
implied. The review explains scope compliance, quality findings and residual risks. Only a
verified main-thread identity can record it. Evidence binds argv, cwd, timestamps,
exit codes, output hashes and exact task runs to the tested source snapshot.
The batch must pass without changing its covered inputs. A relevant source, run,
log or report change invalidates acceptance. Store checks and review inputs under ArtifactRoot.
Every declared -Tests command must appear among executed checks. Use identical argv,
or an explicit sh/bash/zsh -c with the exact command for compound shell checks.

Snapshot coverage: tracked files including deletions and untracked nonignored files;
artifacts are excluded. Ignored dependencies and environment are not covered, so
run appropriate integration checks. Review quality and scope still need judgment.
Standard has no additional spec/quality/final worker requirement. Strict retains
all three, and final verifiers use verify-final-inputs before main-thread acceptance.

## Explicit concern decisions

Standard main review can accept a completed DONE_WITH_CONCERNS report after all
required checks passed. Keep the original report; pass `-DecisionsFile <json>` to
record-main-review. Each current concern-bearing task needs one exact run/report
binding and meaningful dispositions covering every reported concern:

```json
{"decisions":[{"taskId":"widget","runId":"<current-run>","reportSha256":"<original-report-sha256>","concerns":[{"finding":"Local validation does not exercise the optional remote integration","disposition":"accepted-risk","reason":"This task only changes local rendering","evidence":"<relevant-check-log-or-file-reference>"}]}]}
```

Dispositions: accepted-risk, resolved, not-applicable. Main is responsible for the
semantic completeness of that judgment. The runtime checks exact identities,
required explanations, unchanged reports, and real check results. It revalidates
the saved decision receipt. FAIL, BLOCKED, NEEDS_CONTEXT, interrupted execution,
missing tests or failed checks cannot be waived through this mechanism. Strict
retains its independent acceptance requirements.

## Scoped check inputs

Full-project Git input snapshots remain the default. To avoid unrelated changes
invalidating a bounded check, declare every current task's complete inputs during
preparation using `-InputsComplete -ReadScope <shared-code-or-config>` and a
DecisionReason. Include build configuration, shared code, schemas and relevant
lockfiles. If this cannot be established, use full-project checks.

Then run-checks may use repeated `-InputScope <extra-input>` and
`-ScopeReason <why-the-coverage-is-complete>`. The snapshot automatically includes all current
task scopes and read scopes in addition to these inputs; a caller cannot omit a
declared dependency. Plans without complete declarations reject scoped checks.
The evidence pins that selection and plan hashes. Related edits/additions/deletions
invalidate it; unrelated files do not. Symlink inputs are rejected for scoped checks.
Ignored dependencies/environment remain outside Git snapshots; use integration
checks when those matter. This is explicit dependency accounting, not automatic
proof of the project's dependency graph.

## Health and measurement

```sh
python3 <runtime.py> inspect-runs -WorkflowId <id> -ArtifactRoot <artifacts>
python3 <runtime.py> workflow-metrics -WorkflowId <id> -ArtifactRoot <artifacts>
```

Health observes abandoned or stale processes without rewriting status, reports or
leases. Never kill a PID just because it appears in an old artifact. New interrupted
runs record interruption and cannot recover to completed from report text.

Metrics distinguish worker attempts, transport retries, task reruns, native workers,
Claude carriers and main-thread usage. New workflows sample a main-session baseline;
its delta may include other work in that task and excludes output not yet recorded.
Missing values stay null. CLI/provider dollar estimates are not invoices. Historical
runs can lack a main baseline or timing data. Compare similar tasks, including
rework and elapsed time, before claiming that routing saves money.

The 63–75 second orchestration overhead in the 2026-09-05 benchmark is an old
measurement from that setup, not a current estimate or guaranteed saving. Its
recommendation to keep difficult/coupled implementation in main is superseded by
this ownership policy. Measure comparable task quality, rework, critical-path time,
main-context volume, per-layer usage and cost coverage before claiming improvement.
