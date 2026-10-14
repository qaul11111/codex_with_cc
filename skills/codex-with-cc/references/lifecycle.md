# Host lifecycle compatibility

Read the applicable route before dispatch and before finishing. Execution termination and
thread closure are different facts. `interrupt_agent` leaves an agent available;
it is never a substitute for `close_agent`. Do not invent a tool or closure record.
Legacy `claude-code` retains the Codex child -> delegate -> Claude Code chain;
`claude-process` is a separately validated external process with no Codex child.

## Process lifecycle

For `claude-process`, configure `-Policy process-exit` with an actual
active-tool-catalog snapshot containing `exec_command`. This local POSIX route
requires no spawn/close interface. The prepared main-host identity, immutable
plan, exact task commands and bounded timeout are checked before the literal
fixed launcher starts. Existing mixed workflows may retain their thread policy;
their process attempts still require independent process evidence.

Record real process metadata and output, not an agent ID, child marker or
`closeStatus=unsupported` thread claim. Runtime process attempts and receipts bind
start/PID/exit, configuration, original report and stream artifacts. Timeout or
interruption remains unsuccessful; report text cannot recover it to DONE.
Settlement and normal main acceptance are separate. Revalidate receipts before
acceptance and retain every failed attempt. A dead PID alone is insufficient.
Do not kill a process from a stale PID artifact; use the bounded timeout and actual
host execution session for supported cancellation. Undispatched-plan cancellation
does not stop a running process. Local evidence is not tamper-proof attestation.

The remaining lifecycle sections apply to native and legacy Codex child routes.

## Preflight before dispatch

The main thread must inspect its actual active tool catalog and save a JSON snapshot
with `schemaVersion: 1`, `source: "active-tool-catalog"`, and `tools` containing the
observed fully qualified tool names. Do not copy an example capability list or infer
capabilities from documentation. This is a main-thread attestation, not an automatic
host query or a security boundary against same-user modification.

- With `close_agent`, configure `strict-close`. Close and record every attempt.
- Without `close_agent`, use `terminal-evidence` only when local Codex session logs,
  spawn and result/status tools are available on a POSIX host (macOS/Linux).
  The current terminal adapter does not support Windows. Record the limitation up front.
- If neither policy can be satisfied, stop before spawning and explain the missing
  capability. Do not discover the incompatibility only at final acceptance.

```bash
python3 "<installed-workflow-root>/scripts/runtime.py" configure-lifecycle \
  -WorkflowId <workflow-id> -ArtifactRoot <artifact-root> \
  -Policy terminal-evidence -HostToolsFile <actual-host-tools.json>
```

The command validates capabilities before creating a workflow. Use `strict-close`
instead when closure exists. Existing workflows without a policy remain strict;
migration requires explicit user approval and `-MigrateExisting`. Migration saves
an exact backup and policy history; it never edits reports or upgrades BLOCKED to DONE.
Never change the active tool catalog snapshot to bypass a capability check.
Real non-fallback worker launches also reject missing/inconsistent preflight before
calling Claude or the report API. Dry-run/offline test paths remain available but
never supply terminal acceptance evidence.

## Settle every execution attempt

Continue to record every actual spawn immediately with `record-agent-spawn` and
wait for all active children. Under `strict-close`, call the real host close tool
and only after it succeeds use `record-agent-close`.

Under `terminal-evidence`, after the host reports completion, use the original
rollout for that native thread UUID under `$CODEX_HOME/sessions` (default
`~/.codex/sessions`):

```bash
python3 "<installed-workflow-root>/scripts/runtime.py" record-agent-terminal \
  -WorkflowId <workflow-id> -TaskId <task-id> -AgentId <returned-agent-id> \
  -ArtifactRoot <artifact-root> -TranscriptPath <original-rollout.jsonl>
```

This verifies the exact spawn/task/run/thread bindings, project and host provenance,
matching terminal turn, runner completion within that turn, exit code, non-live
runner PID, valid artifacts, and released session lease. It pins SHA-256 hashes of
the raw rollout, configuration, status and report. Full workflow verification
rechecks those proofs; a resumed thread or modified artifact invalidates the proof.
Use a fresh child for rework, never reuse an already settled attempt.

The resulting fields are `executionStatus`, `settledAt`, `executionEvidence` and
`closeStatus: "unsupported"`. This is **not** a closed thread. Once terminal proof
is verified, say “执行已结束；宿主不提供线程关闭接口。” (Execution has ended; the host
does not provide a thread-close interface.) Treat this as capability information,
not an execution failure or an acceptance blocker. Keep the raw field in audit
data. If terminal proof is incomplete, say so without claiming execution ended. Failed and
superseded executions need their own terminal evidence too; settling them does not
make their reports successful. A successfully recorded runner plus an aborted host
turn is insufficient for successful execution proof.

Evidence is local and not a cryptographic host attestation. Missing/rotated logs,
unbound runs, a live or reused PID, unreleased lease, malformed/oversized logs,
dry runs, trusted-local fallbacks, and status recovered from report text are not
eligible. A cancellation before a run was recorded remains blocked; do not fill in
invented metadata. No claim is made that the thread was removed or that arbitrary
detached processes were audited.

Read-only historical audit (no status recovery or report mutation):

```bash
python3 "<installed-workflow-root>/scripts/runtime.py" audit-lifecycle \
  -WorkflowId <workflow-id> -ArtifactRoot <artifact-root>
```

## Final verifier must not require itself to have finished

Before starting the final verifier, settle previous attempts and require current
spec/quality reviews. Its TaskFile should request independent content/tests and:

```bash
python3 "<installed-workflow-root>/scripts/runtime.py" verify-final-inputs \
  -WorkflowId <workflow-id> -ArtifactRoot <artifact-root>
```

This verifies current implementation/review inputs, declared test evidence and
parallel scope safety. It explicitly does **not** certify whole-workflow acceptance.
Do not pass `verify_delegate_workflow` as the final verifier's own required test:
its report and terminal event cannot exist while it is still running.

After its genuine DONE report and host termination, the **main thread** settles or
closes that final attempt and runs `verify_delegate_workflow.*`. The full check still
requires every lifecycle record, accepted current spec and quality reviews, an
accepted final-verifier covering their exact run IDs, declared tests and scope checks.
Retain old BLOCKED reports; a changed lifecycle policy calls for a new final review,
not editing historical results. Restart/reload and use fresh skill context after
updating a plugin whose session hook still injects the old hard-close rule.
