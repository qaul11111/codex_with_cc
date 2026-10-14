# Codex with CC

This contract covers prepared Claude process, native Codex and legacy child routes.

## New workflow profiles and routes

For new workflows read `references/astra-workflows.md` first. Explicitly configured
standard workflows use main-thread review with executed checks and source snapshots;
strict workflows retain independent spec/quality/final-verifier runs. Existing
workflows remain strict. Supported Claude requests prefer `claude-process`: main
invokes the fixed launcher with a prepared task, exact commands and bounded timeout.
No Codex carrier model or child-thread identity is created. Process-exit evidence
and standard main acceptance remain required. The legacy runner contract below
applies to `claude-code`, not to the process route.
Prepared codex-native tasks instead execute directly in a Codex child and import
the original host final response. Model overrides must match the pinned prepared
plan; legacy children keep inherited model/effort. Global model settings are unchanged.

## Required Reading
Read this file only when legacy runner/session details are needed. Current prepared
workflows use `references/astra-workflows.md`; do not preload this entire contract
into main for ordinary task preparation. Treat `contract.json` as the machine-readable source for roles, status tokens, report headings, trigger patterns, required spawn metadata, and forbidden legacy arguments.

## Legacy runner details

For new workflow planning and acceptance, use `references/astra-workflows.md`.
The following describes the transport and compatibility contract. Independent
reviewer/final stages apply to strict only; standard is owned by main.

## Core Contract
1. Requested child-agent, subagent, sub-agent, child-thread, subthread, delegation, worker-execution, 子代理, 子线程, 多代理, 委派, 派工 or 执行层 execution uses a registered workflow. Discussion of agents alone does not require dispatch.
2. Use a registered prepared route, not host worker shortcuts or direct `claude`. Main-thread fixed launch is supported only for validated `claude-process`; direct main-thread `delegate_to_claude.*` remains legacy-incompatible.
3. The Codex main thread owns requirements, design decisions, task boundaries, focused review and final delivery. Simple known-location low-risk tasks may stay in main; delegated workers own exploration, implementation, tests and local repair end to end.
4. Legacy `claude-code` runs use a fresh Codex `spawn_agent` child. Legacy children inherit the main-thread model/effort; prepared legacy plans pin separate carrier settings. Use `fork_context: false` or `fork_turns: "none"`. `claude-process` has no carrier.
5. Legacy child invocation requires `CODEX_CLAUDE_CHILD_THREAD=1` before `delegate_to_claude.*`. Process launch does not assert this marker.
6. Delegate commands must use task-file-only invocation. `-TaskFile`, `-WorkflowId`, `-TaskId`, `-Role`, and `-SessionKey` are required.
7. Legacy inline `-Task`, legacy `-Mode`, missing workflow metadata, and implicit session-key fallback are not supported.
8. Legacy defaults are `high` for implementer/final-verifier and `medium` for other roles. Prepared tasks can pin WorkerEffort per assignment; it is recorded independently of carrier effort.
9. Workers must follow the TaskFile contract: Goal, Allowed Scope, Forbidden Actions, Acceptance Criteria, Verification, and Report Requirements.
10. Task files with empty sections, obvious placeholders, or incomplete Report Requirements are invalid; use `validate_delegate_task.*` before dispatch when preparing non-trivial work.
11. Workers must return all report fields and concrete verification evidence; unambiguous presentation variations are accepted.
12. Strict implementer workflows require accepted `spec` and `quality` reviewer runs plus an accepted `final-verifier` run. Standard workflows require current main-thread review and executable check evidence.

## Trigger Rule
Requests to execute child work trigger workflow routing. Mere discussion does not
start workers. Main may finish simple known-location low-risk small tasks directly.
Substantial exploration or implementation uses end-to-end workers; coupled work
stays in one worker and independent chunks may run in parallel. Main chooses based
on context and risk, without fixed line/file/time thresholds. Claude process routes
use the validated main fixed launcher; `claude-code` retains the legacy chain. Explicitly
prepared codex-native routes use native host execution and verified transcript
import. Unregistered shortcuts and direct main-thread Claude CLI execution remain
unsupported. Read-only version/help/auth-status diagnostics are permitted.

## workflow/task/run Protocol
The protocol models every request as:

- `WorkflowId`: one user-level orchestration.
- `TaskId`: one scoped worker assignment inside that workflow.
- `RunId`: one concrete Claude Code execution attempt for a task.
- `Role`: one of `planner`, `implementer`, `researcher`, `reviewer`, or `final-verifier`.

Artifacts use the current artifact schema. Each run writes `config_<RunId>.json`, `status_<RunId>.json`, `prompt_<RunId>.md`, `stream_<RunId>.jsonl`, `trace_<RunId>.log`, and `claude_<RunId>.md`. Each workflow also writes `workflow_<WorkflowId>.json`, which indexes tasks, runs, scope, verification, review metadata, and final acceptance state.

Reviewer runs must pass `-ReviewForTaskId`, `-ReviewForRunId`, and `-ReviewKind spec` or `-ReviewKind quality`. Reviews bind to one exact implementer run and become stale after the implementer reruns. In strict workflows, implementer tasks are not accepted until both current reviews are accepted. Task dependencies can be recorded with repeated `-DependsOn <task-id>` values.

## Workflow Method
Keep requirements and acceptance explicit without imposing unnecessary handoffs:

1. Design gate: clarify the goal, success criteria, scope, constraints, and acceptance evidence before dispatch.
2. Plan gate: define coherent end-to-end assignments with concise scope, constraints, acceptance and meaningful checks. Do not split discovery, implementation and testing into mandatory separate workers.
3. Dispatch gate: read route-appropriate `references/lifecycle.md` and configure actual host capabilities. Launch admitted process tasks directly through the fixed launcher; native/legacy tasks need a fresh child and no inherited noisy main context. Dispatch independent work within capacity and settle every attempt under its actual lifecycle policy.
4. Implementer gate: workers explore, implement, execute relevant tests and repair locally. Use verification proportional to behavior/risk; test-first or equivalent verification-first evidence is useful for meaningful behavior changes.
5. Focused acceptance: main starts from compact result cards and inspects relevant actual changes/evidence. Standard has no mandatory separate review workers. Strict requires current spec and quality reviewers for requirement coverage and quality.
6. Strict final-verifier gate: use a final verifier to confirm the aggregate workflow, residual risks, declared verification evidence, and accepted review gates.
7. Finish with evidence: ensure current required acceptance checks and artifact/workflow verification; use session-continuity checks only when relevant. Do not repeat passed checks without changed covered inputs/runs, failures or unresolved risk.

If any stage lacks evidence, the main thread must request rework or report the blocker instead of smoothing over the gap.

## TaskFile Contract
Every `-TaskFile` must contain these sections:

- `Goal`: the exact assignment for this worker.
- `Allowed Scope`: files, directories, or behavior the worker may inspect or change.
- `Forbidden Actions`: files, behaviors, and follow-up work the worker must not execute.
- `Acceptance Criteria`: self-checks before reporting.
- `Verification`: exact commands to run, or the smallest meaningful verification expected.
- `Report Requirements`: the required report headings and status rules.

The runtime rejects task files that do not contain these sections, leave required sections empty, retain obvious placeholders, or omit required report headings from `Report Requirements`. Keep sections short and specific; do not copy the whole workflow contract into each
task. Required fields establish scope and evidence, not a reason to micro-delegate.

Pre-dispatch validation:

```powershell
pwsh -NoProfile -File <installed-workflow-root>\windows_scripts\validate_delegate_task.ps1 `
  -TaskFile .\.codex\codex_with_cc\tasks\<task-file>.md `
  -Role implementer `
  -Tests "pytest -q"
```

```bash
"<installed-workflow-root>/macos_scripts/validate_delegate_task.sh" \
  -TaskFile ./.codex/codex_with_cc/tasks/<task-file>.md \
  -Role implementer \
  -Tests "pytest -q"
```

## Platform Hook Gate
Codex automatically discovers `./hooks/hooks.json` from the plugin convention directory and uses it as a semi-hard platform gate. The manifest intentionally omits the unsupported `hooks` field. When hooks are enabled:

- `SessionStart` injects a compact routing contract instead of duplicating this full document.
- `UserPromptSubmit` reinforces the compact routing contract for delegation trigger words.
- `PreToolUse` rejects visible direct `claude` execution and nonliteral launcher invocations. A process fixed launch must pass runtime immutable-plan, admission and main-host validation. Legacy delegate commands retain marker, task/workflow/session, reviewer and parallel-scope checks.

Codex clients that encrypt `collaboration.spawn_agent` messages before `PreToolUse` expose only opaque prompt ciphertext to the hook. For those payloads, the gate enforces inherited model/reasoning metadata and `fork_turns: "none"`; run artifacts and recorded spawn/close lifecycle remain the authoritative proof for the child marker, delegate command, task metadata, and acceptance.

The hook reads `contract.json` for shared tokens. It distinguishes literal heredoc
data and file/path operations from visible command execution, and checks common
wrappers and command substitutions. This is a heuristic command-shape guard, not
a complete shell/interpreter parser or sandbox. It also retains the narrow rejection
of `sed -i` mutations to the fixed launcher; copying its path is not invocation.
Dynamic aliases, constructed code
and same-user artifact tampering need separate runtime/host controls; final
responsibility remains with main.

## Trusted Local Terminal Fallback
This fallback is an execution-location fallback only. Preserve the same `CODEX_CLAUDE_CHILD_THREAD=1` marker, task file, `WorkflowId`, `TaskId`, `Role`, `SessionKey`, session mode, artifact root, scope, and permission flags that the child thread would have used, and pass `-TrustedLocalFallback` so an inherited main-thread `CODEX_THREAD_ID` does not masquerade as child-agent lifecycle evidence.

Do not replace this with the default Codex subagent flow, a direct `claude` command, or a modified worker command. Report that the trusted terminal fallback was used and include the command outcome in verification.

## OpenAI-Compatible Report Runner
`delegate_to_openai_compatible_report.*` is a report-only sibling runner for low-cost workflow judgment, preflight, audit summaries, acceptance reports, and report normalization. It uses the same task-file, workflow metadata, report headings, child-thread marker, and artifact verification contract as the Claude runner, but it must not execute shell tests, modify project files, or perform implementation work.

Configure it with environment variables or a project `.env` file. Environment variables take precedence. By default it reads `DEEPSEEK_API_KEY`, uses base URL `https://api.deepseek.com`, uses model `deepseek-v4-flash`, and waits up to `600` seconds for long-running report model responses. Supported overrides are `DEEPSEEK_BASE_URL` or `DEEPSEEK_API_BASE_URL`, `DEEPSEEK_MODEL`, and `OPENAI_COMPATIBLE_TIMEOUT_SECONDS`; OpenAI-compatible aliases are also accepted. API keys must never be written to artifacts.

## Roles
- Codex main thread: clarify intent, decide boundaries/routing, prepare compact tasks, inspect result cards and targeted evidence, and retain final acceptance. Simple known-location low-risk tasks may be completed directly.
- Codex carrier child (legacy only): invoke the fixed launcher and relay compact results/artifact pointers without duplicate implementation reasoning. Native Codex children execute directly when routing permits. `claude-process` has no carrier.
- Claude Code CLI: explore, implement, execute authorized checks, repair locally and report within assigned scope. Prefer supported process launch and preserve the selected provider; native requires permitted routing.

Worker roles:

- `planner`: read-only task decomposition and acceptance criteria.
- `implementer`: code or file changes inside assigned scope.
- `researcher`: read-only codebase or architecture investigation.
- `reviewer`: spec compliance or quality review for a target implementer task.
- `final-verifier`: workflow-level acceptance and residual risk summary.

Workers resolve routine implementation choices within scope. Main owns product
intent, scope changes and final acceptance. Workers must not create nested delegate
runs, broaden scope or execute unassigned follow-up work. They investigate
discoverable facts themselves; missing intent or authority requires `NEEDS_CONTEXT`.
Return eight-field concise result cards with changed paths, checks, risks and
evidence links. Preserve complete original reports/logs in artifacts instead of
relaying them through main. Main follows relevant evidence and targeted diffs.

## Legacy Session Modes
- `PrimaryReuse`: default for planner, researcher, and implementer serial work. Reuses the main Claude session for continuity.
- `PrimaryAnchor`: parallel-batch anchor. Its result becomes the main reusable context for later serial work.
- `ParallelPool`: default for reviewer and final-verifier independence, and for parallel side work. Uses reusable pool sessions without writing to the main session.

These modes reuse Claude worker sessions only where the runtime can maintain safe
session/lock continuity. They do not reuse Codex host attempts: a settled attempt
always requires a fresh child/descriptor for later work. Verify session continuity
when it matters; do not promise reuse for unsupported routes.

Only use `-AllowParallel` when task scopes are independent. Parallel writable tasks must pass explicit `-Scope` values. After parallel work, return to serial review before accepting implementation changes.

The default session/lock wait is 30 seconds. Claude execution defaults to 3600 seconds for implementers and 1800 seconds for other roles, with a 600-second silent-output timeout and 15-second heartbeat/lease renewal. Override these explicitly only when the task justifies it.

## Native and Legacy Codex Agent Lifecycle
Read `references/lifecycle.md` before the first spawn. Configure `strict-close` when
the host exposes `close_agent`; otherwise explicitly configure `terminal-evidence`
only with supported local host evidence. Stop before dispatch if neither is possible.
Legacy workflows remain strict unless the user approves a backed-up migration.

After each successful `spawn_agent`, record the returned id before waiting:

```bash
python3 "<installed-workflow-root>/scripts/runtime.py" record-agent-spawn \
  -WorkflowId <workflow-id> -TaskId <task-id> -AgentId <agent-id> \
  -ArtifactRoot <artifact-root>
```

Wait on all active ids together. In `strict-close` mode, after the real `close_agent` succeeds, record closure against the same task and id:

```bash
python3 "<installed-workflow-root>/scripts/runtime.py" record-agent-close \
  -WorkflowId <workflow-id> -TaskId <task-id> -AgentId <agent-id> \
  -ArtifactRoot <artifact-root>
```

Every non-fallback child run with `CODEX_THREAD_ID` requires an explicit spawn and a
policy-compliant lifecycle record. In `terminal-evidence` mode use
`runtime.py record-agent-terminal` with original host rollout evidence; closure is
reported as `unsupported`, never `closed`. Missing evidence blocks acceptance.
`interrupt_agent` is not closure. See `references/lifecycle.md` for commands,
evidence requirements, historical audit and limitations.

Current collaboration hosts may return a canonical task handle such as `/root/<task-name>` from spawn while the child runtime exposes a UUID `CODEX_THREAD_ID`. The workflow runtime binds that handle to the UUID only when exactly one unbound spawn exists for the same TaskId; ambiguous candidates remain blocked for explicit resolution.

## Worker Output
Claude Code must return these fields (presentation and order may vary):

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

Status and Final Result must match exactly. `Status` and `Final Result` must use one of:

```text
DONE
DONE_WITH_CONCERNS
NEEDS_CONTEXT
BLOCKED
FAIL
```

Verification must list commands actually run and their outcomes. A `DONE` report without concrete verification evidence is invalid. If verification is blocked, the report must explain the blocker and whether it is unrelated to the delegated change.

The report is evidence, not a success claim by itself. Reviewers and final verifiers should treat missing commands, vague outcomes, role mismatch, status mismatch, or scope drift as acceptance blockers.

## Artifacts
Delegation artifacts are written under `.codex/codex_with_cc/claude-delegate` by default. If that project-local default is not writable, the runtime falls back to a user-level path under `$CODEX_HOME/codex_with_cc/claude-delegate/<project-key>`; explicit `-ArtifactRoot` values are still treated as authoritative and fail fast when unusable.

- `workflow_<WorkflowId>.json`
- `claude_<RunId>.md` for Claude Code runs, or `report_<RunId>.md` for report-only OpenAI-compatible runs
- `status_<RunId>.json`
- `config_<RunId>.json`
- `prompt_<RunId>.md`
- `stream_<RunId>.jsonl`
- `trace_<RunId>.log`
- `session-pools/<SessionKey>.json`

Use `verify_delegate_run.*` or `verify_delegate_artifacts.*` for each run, `verify_delegate_workflow.*` for the workflow aggregate, and `verify_delegate_chain.*` for multi-run session continuity checks. `verify_delegate_workflow.*` enforces review gates, the final-verifier gate, declared `-Tests` evidence for non-dry-run `DONE` reports, and non-overlapping parallel implementer scopes. The shared implementation lives under `scripts/*.py`; platform wrappers stay thin.

Final-verifier TaskFiles must use `runtime.py verify-final-inputs` for input checks
plus independent content/tests, not require their own `verify_delegate_workflow`
to pass before their report exists. The main thread runs whole-workflow verification
after the final report and lifecycle settlement. This separation does not waive
current spec, quality, final-verifier or lifecycle gates.

`<installed-workflow-root>` means the installed `skills/codex-with-cc` directory, for example `<codex-home>/plugins/cache/aiskyhub/codex-with-cc/<version-or-hash>/skills/codex-with-cc`. Do not use the package root `<version-or-hash>` directory.

## Fixed Launcher (macOS 1.2.0+)

The hand-written descriptor and marker details below are legacy `claude-code`
compatibility examples. `claude-process` instead uses generated immutable plans
and `invocation: codex_with_cc_process`; follow the prepared process guide and do
not add a child marker or reuse this manual child descriptor.

Codex App approval works best with a single stable command that takes no arguments. The fixed launcher uses a versioned `launch.json` descriptor placed in one directory per child attempt.

### Install the stable launcher

```bash
"<installed-workflow-root>/macos_scripts/install-codex-with-cc-launch.sh"
```

This writes the no-argument executable `${CODEX_HOME:-$HOME/.codex}/bin/codex-with-cc-launch`. The file is idempotent: rerunning the installer overwrites it with the current `<installed-workflow-root>`. Keep the launcher on a user-writable path and ensure it is executable.

### Prepare a descriptor directory

For each child thread attempt, create a dedicated directory containing `launch.json`. Do not share descriptor directories across concurrent attempts; use one directory per `TaskId`/`RunId`.

```bash
launch_dir="./.codex/codex_with_cc/launcher-runs/<workflow-id>/<task-id>/<run-id>"
mkdir -p "$launch_dir"
cat > "$launch_dir/launch.json" <<'JSON'
{
  "version": "1.2.0",
  "invocation": "codex_with_cc_workflow",
  "childThread": {
    "threadId": "<CODEX_THREAD_ID of this child thread>"
  },
  "projectWorkingDirectory": "<absolute project root>",
  "taskFile": "./.codex/codex_with_cc/tasks/<yyyyMMdd>/<HHmmssfff>-<short-id>-<task>.md",
  "workflowId": "<workflow-id>",
  "taskId": "<task-id>",
  "role": "implementer",
  "sessionKey": "<stable-session-key>",
  "scope": ["<changed-or-inspected-path>"],
  "tests": ["pytest -q"],
  "session": {
    "sessionMode": "PrimaryReuse",
    "allowParallel": false
  },
  "bypassPermissions": true
}
JSON
```

### Invoke the stable launcher

The terminal tool sets the descriptor directory as its working directory, then executes the exact literal no-argument launcher command:

```bash
/Users/<user>/.codex/bin/codex-with-cc-launch
```

Codex App normally records that terminal command as argv `["/bin/zsh", "-c", "/Users/<user>/.codex/bin/codex-with-cc-launch"]`. Do not put an additional `zsh -c` wrapper in the terminal tool command.

The launcher:

- Accepts **no command-line arguments**.
- Sets `CODEX_CLAUDE_CHILD_THREAD=1`.
- Requires `CODEX_THREAD_ID` to match `childThread.threadId` during normal child execution. An explicit `trustedLocalFallback: true` descriptor maps to `-TrustedLocalFallback` and is the only way to bypass equality.
- Validates the descriptor schema, required fields, unknown sub-fields, list element types, role, review metadata, session mode, integer ranges, and boolean types.
- Verifies that the descriptor directory and `launch.json` are owned by the current user and not group/other writable, with no symlinks in any path component.
- Requires `projectWorkingDirectory` to be absolute, existing, owned by the current user, not group/other writable, and symlink-free.
- Requires `taskFile` to be relative, reject `..`, resolve inside `projectWorkingDirectory`, and reject absolute/symlinked task paths.
- Claims the descriptor atomically with a `claimed` file (owner-only, `0o600`); a second run in the same directory fails.
- Executes the existing `delegate_to_claude.py` runtime inside `projectWorkingDirectory`.

### Exact narrow Codex exec-policy example

Use this `.rules` example in the Codex App to approve only the stable launcher with no arguments. Do **not** add this rule to the user's live config automatically; document it and let the user enable it.

```starlark
prefix_rule(pattern=["/bin/zsh", "-c", "/Users/<user>/.codex/bin/codex-with-cc-launch"], decision="allow")
```

See `examples/exec-policy.example.rules`. Only allow the three-element App-recorded argv. Do not add a one-element launcher `prefix_rule`, because prefix rules also match commands with later arguments.

### Concurrency and isolation

- Use one descriptor directory per child attempt.
- Do not write a global "current" pointer file that multiple attempts update.
- The atomic `claimed` file prevents accidental double execution of the same descriptor.
- Parallel tasks keep independent directories, independent artifacts, and independent `CODEX_THREAD_ID` values.

### Upgrade and rollback

- Upgrade: run `install-codex-with-cc-launch.sh` from the new plugin version. The launcher resolves the new workflow root on its next invocation.
- Rollback: overwrite `${CODEX_HOME:-$HOME/.codex}/bin/codex-with-cc-launch` with the previous version's launcher, or remove the file and reinstall from the desired plugin version.
- Do not delete old launcher versions from under running child threads.

### Security boundaries

- The launcher must not accept command-line arguments or environment variables that override descriptor fields.
- Descriptor directories and `launch.json` are verified for ownership (current user) and mode (no group/other write).
- No symlinks in `projectWorkingDirectory`, `taskFile`, or any unresolved path component.
- The launcher validates that `projectWorkingDirectory` is writable and `taskFile` is readable.
- `taskFile` must be relative and resolve inside `projectWorkingDirectory`; absolute, `..`, and escaped paths are rejected.
- Only an explicit `trustedLocalFallback: true` skips the `CODEX_THREAD_ID` equality check; it maps to the existing runtime fallback flag and still requires a valid task file and descriptor schema.
- The installer writes atomically, checks ownership of `CODEX_HOME` and `CODEX_HOME/bin`, and embeds the current `sys.executable`.

## Standard Worker Command (legacy argument-based entrypoint)

The argument-based delegate scripts remain supported for backwards compatibility. New integrations should prefer the fixed launcher.

Windows:

```powershell
$workflowRoot = '<installed-workflow-root>'
$env:CODEX_CLAUDE_CHILD_THREAD = '1'
pwsh -NoProfile -File (Join-Path $workflowRoot 'windows_scripts\delegate_to_claude.ps1') `
  -TaskFile .\.codex\codex_with_cc\tasks\<yyyyMMdd>\<HHmmssfff>-<short-id>-<task-file>.md `
  -WorkflowId <workflow-id> `
  -TaskId <task-id> `
  -Role implementer `
  -SessionKey <stable-session-key> `
  -Scope <changed-or-inspected-path> `
  -SessionMode PrimaryReuse `
  -BypassPermissions
```

macOS:

```bash
WORKFLOW_ROOT="<installed-workflow-root>"
export CODEX_CLAUDE_CHILD_THREAD=1
"$WORKFLOW_ROOT/macos_scripts/delegate_to_claude.sh" \
  -TaskFile ./.codex/codex_with_cc/tasks/<yyyyMMdd>/<HHmmssfff>-<short-id>-<task-file>.md \
  -WorkflowId <workflow-id> \
  -TaskId <task-id> \
  -Role implementer \
  -SessionKey <stable-session-key> \
  -Scope <changed-or-inspected-path> \
  -SessionMode PrimaryReuse \
  -BypassPermissions
```

Reviewer runs add `-Role reviewer -ReviewForTaskId <implementer-task-id> -ReviewForRunId <current-implementer-run-id> -ReviewKind spec` or the same command with `-ReviewKind quality`.

## Verification
Run local regression tests after installing or changing this workflow.

Windows:

```powershell
$workflowRoot = '<installed-workflow-root>'
pwsh -NoProfile -File (Join-Path $workflowRoot 'windows_scripts\test_delegate_runtime.ps1')
pwsh -NoProfile -File (Join-Path $workflowRoot 'windows_scripts\test_delegate_session_pool.ps1')
```

macOS:

```bash
WORKFLOW_ROOT="<installed-workflow-root>"
"$WORKFLOW_ROOT/macos_scripts/test_delegate_runtime.sh"
"$WORKFLOW_ROOT/macos_scripts/test_delegate_session_pool.sh"
```

Verify a run and workflow with `verify_delegate_run.*` and `verify_delegate_workflow.*`.
