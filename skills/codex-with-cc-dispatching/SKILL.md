---
name: codex-with-cc-dispatching
description: Dispatch codex-with-cc tasks through the required Codex child thread to delegate_to_claude.* to Claude Code CLI chain with WorkflowId, TaskId, Role, and Scope metadata.
---

# Codex with CC Dispatching

Read `../codex-with-cc/CODEX_WITH_CC.md` before dispatching. Use this skill after planning has produced task boundaries.

Dispatch rules:

- Every child thread inherits the main-thread model and reasoning effort; omit `fork_context` or set it to `false`.
- Every worker command sets `CODEX_CLAUDE_CHILD_THREAD=1`.
- Every worker command passes `-TaskFile`, `-WorkflowId`, `-TaskId`, `-Role`, and `-SessionKey`.
- Run `validate_delegate_task.*` before dispatch when the task file was generated, contains reviewer metadata, or carries explicit `-Tests` commands.
- Never dispatch legacy inline `-Task`, legacy `-Mode`, or a command that relies on an implicit session key.
- Reviewer commands must pass `-ReviewForTaskId`, the current implementer `-ReviewForRunId`, and `-ReviewKind spec` or `-ReviewKind quality`.
- Parallel writable tasks require explicit non-overlapping `-Scope` values.
- Use `PrimaryAnchor` for a parallel batch anchor, `ParallelPool` for independent side work, and `PrimaryReuse` for serial follow-up.

Dispatch discipline:

- Dispatch the immediate blocking task locally only when no child-thread delegation is needed; otherwise create the Codex child thread and keep the main thread focused on review.
- Put all worker instructions in a TaskFile with `Goal`, `Allowed Scope`, `Forbidden Actions`, `Acceptance Criteria`, `Verification`, and `Report Requirements`; the runtime rejects old one-line prompts.
- Include the exact verification commands in the task file and pass them with `-Tests` when possible.
- The worker's final `Verification` report must include every command passed with `-Tests` and the observed outcome.
- Dispatch implementer, spec reviewer, and quality reviewer as separate task ids so the workflow artifact can prove acceptance.
- Dispatch a final-verifier task for any workflow with implementer tasks.
- Use parallel dispatch only after scope boundaries are explicit enough to avoid file conflicts.
- Spawn all independent tasks before the first wait. Wait on all active agent ids in one call and process whichever completes first.
- Record each returned id with `runtime.py record-agent-spawn`. Close every completed, failed, interrupted, or replaced attempt, then record it with `runtime.py record-agent-close`.
- After a parallel batch, wait for the anchor and side tasks before serial review or follow-up implementation.

Do not dispatch default Codex workers outside the codex-with-cc chain.
