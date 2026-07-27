# Codex with CC

This is the portable contract for the Codex main thread -> Codex child thread -> Claude Code CLI workflow.

## Required Reading
Read this file before using the workflow in this repository. Treat `contract.json` as the machine-readable source for roles, status tokens, report headings, trigger patterns, required spawn metadata, and forbidden legacy arguments.

## Core Contract
1. Any child-agent, subagent, sub-agent, child-thread, subthread, delegation, worker-execution, 子代理, 子线程, 多代理, 委派, 派工, or 执行层 request must use this workflow.
2. Do not replace it with the default Codex subagent flow, host worker shortcuts, direct `claude`, or direct main-thread `delegate_to_claude.*`.
3. The Codex main thread owns design, task boundaries, acceptance criteria, review decisions, rework decisions, and final delivery.
4. Every Claude Code worker run must be carried by a fresh Codex `spawn_agent` child thread that inherits the main-thread model and reasoning effort; use `fork_context: false` or the current host equivalent `fork_turns: "none"`.
5. The child thread must set `CODEX_CLAUDE_CHILD_THREAD=1` before invoking `delegate_to_claude.*`.
6. Delegate commands must use task-file-only invocation. `-TaskFile`, `-WorkflowId`, `-TaskId`, `-Role`, and `-SessionKey` are required.
7. Legacy inline `-Task`, legacy `-Mode`, missing workflow metadata, and implicit session-key fallback are not supported.
8. The runner selects Claude effort by role: `high` for implementer/final-verifier and `medium` for planner/researcher/reviewer.
9. Workers must follow the TaskFile contract: Goal, Allowed Scope, Forbidden Actions, Acceptance Criteria, Verification, and Report Requirements.
10. Task files with empty sections, obvious placeholders, or incomplete Report Requirements are invalid; use `validate_delegate_task.*` before dispatch when preparing non-trivial work.
11. Workers must finish with the exact report headings and concrete verification evidence.
12. Implementer workflows require accepted `spec` and `quality` reviewer runs plus an accepted `final-verifier` run before workflow acceptance.

## Trigger Rule
Any user mention of child-agent, subagent, sub-agent, child-thread, subthread, delegation, worker-execution, or Chinese equivalents such as 子代理、子线程、多代理、委派、派工、执行层 is a workflow trigger. When triggered, the main Codex thread must use this custom delegation workflow and must not satisfy the request with the default Codex subagent flow, a host-provided agent shortcut, direct `claude` execution, or direct main-thread execution of `delegate_to_claude.*`.

## workflow/task/run Protocol
The protocol models every request as:

- `WorkflowId`: one user-level orchestration.
- `TaskId`: one scoped child-thread assignment inside that workflow.
- `RunId`: one concrete Claude Code execution attempt for a task.
- `Role`: one of `planner`, `implementer`, `researcher`, `reviewer`, or `final-verifier`.

Artifacts use the current artifact schema. Each run writes `config_<RunId>.json`, `status_<RunId>.json`, `prompt_<RunId>.md`, `stream_<RunId>.jsonl`, `trace_<RunId>.log`, and `claude_<RunId>.md`. Each workflow also writes `workflow_<WorkflowId>.json`, which indexes tasks, runs, scope, verification, review metadata, and final acceptance state.

Reviewer runs must pass `-ReviewForTaskId`, `-ReviewForRunId`, and `-ReviewKind spec` or `-ReviewKind quality`. Reviews bind to one exact implementer run and become stale after the implementer reruns. Implementer tasks are not workflow-accepted until both current reviews are accepted. Task dependencies can be recorded with repeated `-DependsOn <task-id>` values.

## Workflow Method
Use this as a controlled delivery pipeline, borrowing the core discipline from Superpowers:

1. Design gate: clarify the goal, success criteria, scope, constraints, and acceptance evidence before dispatch.
2. Plan gate: split work into task-file-sized assignments with explicit allowed scope, forbidden actions, verification commands, and review gates.
3. Dispatch gate: create a fresh child thread per task; do not let workers inherit noisy main-thread context. Spawn every independent task before waiting, batch-wait on all active ids, and close every completed, failed, interrupted, or replaced attempt.
4. Implementer gate: implementation workers must use test-first or the smallest equivalent verification-first evidence when the repository has a practical test surface.
5. Review in two passes. First perform spec compliance review; then perform quality review for minimality, maintainability, regression risk, and test sufficiency.
6. Final-verifier gate: use a final verifier to confirm the aggregate workflow, residual risks, declared verification evidence, and accepted review gates.
7. Finish with evidence: run artifact verification, workflow verification, session continuity checks when relevant, and repository regression tests.

If any stage lacks evidence, the main thread must request rework or report the blocker instead of smoothing over the gap.

## TaskFile Contract
Every `-TaskFile` must contain these sections:

- `Goal`: the exact assignment for this worker.
- `Allowed Scope`: files, directories, or behavior the worker may inspect or change.
- `Forbidden Actions`: files, behaviors, and follow-up work the worker must not execute.
- `Acceptance Criteria`: self-checks before reporting.
- `Verification`: exact commands to run, or the smallest meaningful verification expected.
- `Report Requirements`: the required report headings and status rules.

The runtime rejects task files that do not contain these sections, leave required sections empty, retain obvious placeholders, or omit required report headings from `Report Requirements`. This makes worker context explicit and prevents old one-line prompts from acting as hidden orchestration.

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
- `PreToolUse` denies visible direct `claude`, direct main-thread `delegate_to_claude.*`, missing `CODEX_CLAUDE_CHILD_THREAD=1`, missing `-TaskFile`, missing workflow metadata, missing `-SessionKey`, legacy `-Task`, legacy `-Mode`, reviewer runs without review metadata, and parallel writable runs without `-Scope`.

Codex clients that encrypt `collaboration.spawn_agent` messages before `PreToolUse` expose only opaque prompt ciphertext to the hook. For those payloads, the gate enforces inherited model/reasoning metadata and `fork_turns: "none"`; run artifacts and recorded spawn/close lifecycle remain the authoritative proof for the child marker, delegate command, task metadata, and acceptance.

The hook reads `contract.json` for shared tokens. This is not a kernel boundary; final responsibility remains with the Codex main thread.

## Trusted Local Terminal Fallback
This fallback is an execution-location fallback only. Preserve the same `CODEX_CLAUDE_CHILD_THREAD=1` marker, task file, `WorkflowId`, `TaskId`, `Role`, `SessionKey`, session mode, artifact root, scope, and permission flags that the child thread would have used, and pass `-TrustedLocalFallback` so an inherited main-thread `CODEX_THREAD_ID` does not masquerade as child-agent lifecycle evidence.

Do not replace this with the default Codex subagent flow, a direct `claude` command, or a modified worker command. Report that the trusted terminal fallback was used and include the command outcome in verification.

## OpenAI-Compatible Report Runner
`delegate_to_openai_compatible_report.*` is a report-only sibling runner for low-cost workflow judgment, preflight, audit summaries, acceptance reports, and report normalization. It uses the same task-file, workflow metadata, report headings, child-thread marker, and artifact verification contract as the Claude runner, but it must not execute shell tests, modify project files, or perform implementation work.

Configure it with environment variables or a project `.env` file. Environment variables take precedence. By default it reads `DEEPSEEK_API_KEY`, uses base URL `https://api.deepseek.com`, uses model `deepseek-v4-flash`, and waits up to `600` seconds for long-running report model responses. Supported overrides are `DEEPSEEK_BASE_URL` or `DEEPSEEK_API_BASE_URL`, `DEEPSEEK_MODEL`, and `OPENAI_COMPATIBLE_TIMEOUT_SECONDS`; OpenAI-compatible aliases are also accepted. API keys must never be written to artifacts.

## Roles
- Codex main thread: clarify intent, approve design, define task files, create child threads, review results, request rework, and decide final acceptance.
- Codex child thread: provide the visible conversation-tree node and invoke the worker script.
- Claude Code CLI: execute the delegated task, run verification, and produce a structured report.

Worker roles:

- `planner`: read-only task decomposition and acceptance criteria.
- `implementer`: code or file changes inside assigned scope.
- `researcher`: read-only codebase or architecture investigation.
- `reviewer`: spec compliance or quality review for a target implementer task.
- `final-verifier`: workflow-level acceptance and residual risk summary.

Workers are context consumers, not decision owners. They must not create nested delegate runs, broaden scope, or decide that unassigned follow-up work should be executed. When a worker lacks context, it reports `NEEDS_CONTEXT`.

## Session Modes
- `PrimaryReuse`: default for planner, researcher, and implementer serial work. Reuses the main Claude session for continuity.
- `PrimaryAnchor`: parallel-batch anchor. Its result becomes the main reusable context for later serial work.
- `ParallelPool`: default for reviewer and final-verifier independence, and for parallel side work. Uses reusable pool sessions without writing to the main session.

Only use `-AllowParallel` when task scopes are independent. Parallel writable tasks must pass explicit `-Scope` values. After parallel work, return to serial review before accepting implementation changes.

The default session/lock wait is 30 seconds. Claude execution defaults to 3600 seconds for implementers and 1800 seconds for other roles, with a 600-second silent-output timeout and 15-second heartbeat/lease renewal. Override these explicitly only when the task justifies it.

## Codex Agent Lifecycle
After each successful `spawn_agent`, record the returned id before waiting:

```bash
python3 "<installed-workflow-root>/scripts/runtime.py" record-agent-spawn \
  -WorkflowId <workflow-id> -TaskId <task-id> -AgentId <agent-id> \
  -ArtifactRoot <artifact-root>
```

Wait on all active ids together. After `close_agent` succeeds, record closure against the same task and id:

```bash
python3 "<installed-workflow-root>/scripts/runtime.py" record-agent-close \
  -WorkflowId <workflow-id> -TaskId <task-id> -AgentId <agent-id> \
  -ArtifactRoot <artifact-root>
```

Every non-fallback child run with `CODEX_THREAD_ID` requires explicit spawn and close records. Missing or unclosed attempts block final acceptance.

Current collaboration hosts may return a canonical task handle such as `/root/<task-name>` from spawn while the child runtime exposes a UUID `CODEX_THREAD_ID`. The workflow runtime binds that handle to the UUID only when exactly one unbound spawn exists for the same TaskId; ambiguous candidates remain blocked for explicit resolution.

## Worker Output
Claude Code must finish with these exact headings:

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

`<installed-workflow-root>` means the installed `skills/codex-with-cc` directory, for example `<codex-home>/plugins/cache/aiskyhub/codex-with-cc/<version-or-hash>/skills/codex-with-cc`. Do not use the package root `<version-or-hash>` directory.

## Fixed Launcher (macOS 1.2.0+)

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
