# Native Codex Agents Design

## Objective

Turn the `codex_with_cc` fork into a Native Codex Only plugin. Preserve the
upstream workflow discipline while replacing the Claude Code delegation layer
with Codex's built-in `spawn_agent`, `wait_agent`, `send_input`, and
`close_agent` tools.

The first release is a hard fork. It does not retain Claude Code, CC Switch,
DeepSeek, or an OpenAI-compatible report backend.

## Product Boundary

The plugin remains an orchestration policy for Codex rather than a separate
agent daemon. Skills and hooks tell the main Codex thread how to plan, dispatch,
review, and verify work. Small local helpers validate task and workflow records,
but they do not attempt to call Codex's internal agent tools themselves.

The working plugin name is `codex-native-agents`. The GitHub repository may
remain `codex_with_cc` during development so the fork relationship and history
stay obvious. Repository renaming is independent of the first functional
release.

## Retained Contracts

The fork keeps these upstream ideas:

- One `WorkflowId` per user request and one stable `TaskId` per delegated task.
- Worker roles: `planner`, `implementer`, `researcher`, `reviewer`, and
  `final-verifier`.
- Task files with `Goal`, `Allowed Scope`, `Forbidden Actions`, `Acceptance
  Criteria`, `Verification`, and `Report Requirements`.
- Structured worker reports with `Status`, `Role`, `Summary`, `Changed Files`,
  `Verification`, `Findings`, `Final Result`, and `Risks Or Follow-ups`.
- Status values: `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, `BLOCKED`, and
  `FAIL`.
- Explicit non-overlapping scopes for parallel writable tasks.
- Separate spec review, quality review, and final verification gates for
  implementation workflows.
- Main-thread ownership of architecture, task boundaries, rework decisions,
  acceptance, and final delivery.

## Native Execution Flow

1. The main thread decides whether delegation materially helps the request.
2. It creates and validates bounded task files.
3. It selects a model profile for each task and calls native `spawn_agent` with
   `fork_context: false`.
4. Independent tasks are spawned in the same dispatch round. Writable tasks
   may run in parallel only when their scopes are disjoint.
5. Each child reads its task file, follows repository instructions, performs
   the assigned work, verifies it, and returns the structured report.
6. The main thread reviews results and requests rework through `send_input` or a
   fresh higher-tier agent when escalation is justified.
7. Implementer output passes spec review, quality review, and final verification
   before acceptance.
8. Completed agents are closed promptly and the workflow record is finalized.

Every child prompt includes a machine-readable task envelope containing
`WorkflowId`, `TaskId`, `Role`, `TaskFile`, and `Scope`. Child agents may not
create nested agents. The main thread is the only dispatcher.

## Model Routing

The default policy optimizes for capability per unit of usage rather than
forcing every child to inherit the most expensive parent model.

| Work type | Default model | Reasoning effort |
| --- | --- | --- |
| Focused research, exploration, and mechanical edits | `gpt-5.6-luna` | `medium` |
| Normal implementation and spec review | `gpt-5.6-terra` | `medium` |
| Complex implementation and quality review | `gpt-5.6-terra` | `high` |
| Architecture disputes, high-risk review, and final verification | `gpt-5.6-sol` | `high` |

Routing is a soft policy stored in the machine-readable contract. Hooks do not
hard-fail solely because a configured model name is unavailable. If Codex no
longer exposes a configured model, dispatch falls back to parent inheritance
and records the fallback in the workflow report.

A failed or blocked task may escalate by one tier at most once. Repeated failure
returns control to the main thread instead of starting an unbounded retry loop.
Exact monetary prices and quota multipliers are outside the first release
because the current native tool exposes relative tiers, not a stable billing
contract.

## Components

### Core Skill

`codex-native-agents` is the mandatory entry point for explicit subagent,
delegation, or multi-agent requests. It defines when delegation is useful and
keeps trivial work in the main thread.

### Workflow Skills

Planning, dispatching, worker, reviewing, and finishing skills are retained but
rewritten around native Codex tools. They share one `contract.json` and do not
duplicate model or report rules.

### Hooks

- `SessionStart` injects the compact native workflow contract.
- `UserPromptSubmit` reinforces it only when delegation trigger terms appear.
- `PreToolUse` validates required task-envelope metadata, forbids child-agent
  recursion, and rejects unsafe parallel writable scopes.

Hooks validate stable protocol fields. They do not enforce a permanently fixed
model slug, invoke shell delegates, or block ordinary main-thread work merely
because a prompt mentions an agent-related word in documentation or code.

### Validation Runtime

The retained Python runtime is reduced to:

- task-file validation;
- workflow and task record updates;
- structured report validation;
- scope-overlap checks;
- review-gate and final-acceptance verification.

Artifacts live under `.codex/codex_native_agents/` in the target project and
record native agent IDs, selected model profiles, fallbacks, status, reports,
and verification evidence. Raw model streams and provider session state are not
stored.

## Removed Components

The implementation removes:

- `delegate_to_claude` entry points and Claude CLI process management;
- Claude session pools, leases, resume logic, and session modes;
- `CODEX_CLAUDE_CHILD_THREAD` and PATH discovery for `claude`;
- CC Switch and DeepSeek-specific instructions;
- thinking-strip proxy scripts;
- OpenAI-compatible report runners;
- Windows and macOS wrappers whose only purpose is launching Claude;
- Claude-specific examples, tests, documentation, and artifact fields;
- the `ccviz` surface until a native workflow record proves a dashboard is
  worth maintaining.

## Failure Handling

- Invalid task files fail before dispatch.
- Missing native agent tools produce `BLOCKED` with a clear host requirement.
- Unavailable configured models fall back to parent inheritance and are
  reported, not silently ignored.
- A child returning `NEEDS_CONTEXT` receives narrowly scoped context through
  `send_input`; it does not receive the full parent conversation by default.
- Conflicting writable scopes force serial execution.
- Reviewer rejection prevents final acceptance and routes the task back to the
  implementer or to a one-tier escalation.
- Interrupted or errored agents are closed and recorded before replacement.

## Testing

Automated tests cover:

- plugin and hook manifest schemas;
- trigger matching without broad false positives;
- task-envelope and task-file validation;
- role-to-model routing and unavailable-model fallback;
- parallel scope conflict detection;
- report parsing and status consistency;
- spec, quality, and final-verifier acceptance gates;
- removal of Claude-specific commands and environment requirements.

Mocks cover model routing and lifecycle edge cases without consuming agent
quota. Manual smoke verification covers one Luna research task, one Terra
implementation task, one Sol final-verifier task, and a two-agent parallel
read-only batch. A smoke run is accepted only when all agents close cleanly and
the workflow record passes validation.

## Migration And Compatibility

The old `codex-with-cc` plugin must be disabled before the native plugin is
enabled because both claim the same delegation triggers. No compatibility shim
or automatic fallback to Claude is provided.

The first development install is local and user-scoped. Marketplace packaging,
repository renaming, and public release metadata follow only after the native
smoke workflow passes.

## Acceptance Criteria

- No runtime path invokes or requires Claude Code, CC Switch, DeepSeek, or an
  external report model.
- Explicit delegated tasks use native Codex child agents.
- Luna, Terra, and Sol are selected according to the contract with a safe
  inheritance fallback.
- Independent tasks can run in parallel without overlapping writable scopes.
- Implementer workflows cannot be accepted without spec, quality, and final
  verification evidence.
- The plugin installs alongside no enabled legacy delegation hook and passes
  unit, contract, and real native-agent smoke verification.
