---
name: codex-native-agents
description: Assess decomposition before substantial development or investigation, then dispatch eligible native GPT-6.1 Sol, GPT-6 Astra and Luna subagents or explain direct execution. Cooperate with the task's multi-agent mode, user limits and actual host support.
---

# Codex Native Agents

The main thread owns dispatch, architecture, scope, acceptance, and delivery.
For substantial authorized development or investigation, this skill explicitly
requests delegation of eligible independent work, subject to the assessment below.
This request satisfies a host mode that permits delegation when an applicable
skill explicitly asks for it. It does not override a host prohibition, a user
restriction, missing tools, or expand the authorized scope.
Workers cannot call `spawn_agent` recursively or expand the assignment.

## Assess before substantial execution

Before broad investigation, implementation or workflow creation, main must assess
the task's multi-agent mode, user limits, candidate independent work, useful work
remaining for main, and dispatch/review cost. A brief initial inspection is fine
when needed to identify boundaries. Do not finish the whole task first and justify
the lack of delegation afterward.

- Read the actual current mode instructions. Proactive delegation may be enabled,
  require an explicit user/AGENTS/skill request, or be prohibited. In the middle
  case, this applicable skill supplies the explicit request; do not call that
  mode an absolute prohibition. A hard prohibition or user no-agent restriction
  wins. Do not toggle the task's mode or use another runtime to bypass it.
- State the assessment briefly in the user's language: the concrete worker task,
  what main will do concurrently, and the intended model, or a specific reason
  for direct execution. For example: "Sol will inspect the isolated parser tests;
  I will trace the unrelated transport failure." If direct, name the coupling,
  missing capability, serial restriction, or insufficient benefit. "Main can do
  it" and "the main model is Astra" are not reasons to skip eligible delegation.
- Native dispatch requires `spawn_agent` and `wait_agent` (or legacy `wait`).
  `list_agents` is optional; if absent, track returned agent IDs and retain the
  existing concurrency, terminal-evidence and close checks. Never invent a tool
  or substitute a chat-listing API in the capability snapshot.
- If the split is useful and allowed, perform capability preflight, prepare and
  dispatch it. An assessment alone does not fulfill an eligible dispatch. If
  preflight or admission blocks it, explain the actual blocker and continue
  authorized main work; do not invent a worker or ask again for routine permission.
- Reassess when scope grows, a blocker opens independent work, or the mode/user
  constraints change. Small direct fixes need no workflow or ceremonial status;
  when the user requests agents, explain any decision not to dispatch even for
  a small task. A mention of agents in quoted material is not a dispatch request.

Use `advise` when a recorded decision helps. Supply mode and request source from
the current instructions, not from model choice or a previous task. Its output
is planning advice; it neither discovers mode nor grants permission.

## Choose a useful split

- Keep small fixes, uncertain design choices, tightly coupled edits and short
  investigations in main. Complexity alone does not justify delegation.
- Delegate a bounded task when an independent worker can make progress while
  main does useful work and the expected benefit exceeds dispatch/review cost.
- Parallelize independent tasks only after mapping dependencies and all files
  they may read/write. Multiple readers may share scope. A writer conflicts
  with readers and writers in its scope. Serialize shared indexes, lockfiles,
  generated catalogs and integration changes under one owner.
  Ordered writers may share scope only with an explicit direct or transitive
  dependency; the later task still waits for successful terminal settlement.
- Default to standard acceptance: main reviews the actual diff and executes
  relevant checks. Choose strict before dispatch for high-risk changes or
  explicitly requested independent reviews. Do not downgrade a running workflow.
- Use Luna low for focused work, 6.1 Sol medium for ordinary work, 6.1 Sol high
  for deeper implementation/review, and 6.1 Sol xhigh for complex planning/review.
  Use Astra xhigh for high-risk work, strict final verification and escalation
  after a diagnosed Sol capability/quality failure. Classify risk separately:
  complexity alone does not require Astra or strict acceptance. Use `--risk high`
  for security/privacy boundaries, irreversible data changes, financial decisions
  or similarly consequential uncertainty; legacy `--complexity high-risk` also
  remains high risk and cannot be downgraded with `--risk normal`. Main chooses
  role/complexity/risk; runtime
  checks the exact model/effort against the active host catalog and records the
  selection reason. An unavailable automatic route can move to a stronger
  supported profile; if none exists, keep work in main. Never alias GPT-5.6 to 6.
- Preserve an explicitly chosen profile with `--model-profile`; it cannot be
  silently replaced or escalated. Automatic failed attempts may escalate once:
  Luna to 6.1 Sol, any 6.1 Sol profile directly to Astra. Prepare a fresh attempt after terminal settlement.
  After the second attempt, or at the top profile, return to main. Resolve missing
  context, unavailable tools or permissions before considering a stronger model.
  `NEEDS_CONTEXT` and `BLOCKED` cannot escalate. Other retry candidates require
  `--escalation-cause capability|quality` and an evidence-based `--escalation-note`;
  a failed or interrupted run alone does not establish a model capability problem.

New automatic routes use 6.1 Sol profiles; `balanced`/`balancedHigh` retain their
original GPT-6 Sol pairs only for existing tasks and explicit pins. Do not rename
old receipts or treat GPT-6 Sol as an alias for GPT-6.1 Sol. Standard acceptance
uses current checks and main review, without a redundant final-verifier worker.

Keep the user's main-session model unchanged. Dispatch coherent assignments with
the minimum sufficient context and concise result cards; do not fill every slot
or split a short task merely to use all three models. The `route` command previews
selection without dispatch. These rules automate decisions through the main
agent; they are not a background service or a claim of measured cost savings.
Returning control to main does not waive a user's model restriction: if the user
requires Sol only and Sol is unavailable, report the limitation instead of having
an Astra main thread perform the restricted work.

When delegating, read [CODEX_NATIVE_AGENTS.md](CODEX_NATIVE_AGENTS.md) and
[the command guide](references/adaptive-workflows.md). Read stage skills only
for the current stage. `contract.json` supplies model/role defaults.

## Native task envelope

```text
[NATIVE_CODEX_AGENT_TASK]
WorkflowId: native-auth-workflow
TaskId: auth-token-implementation
Role: implementer
TaskFile: .codex/codex_native_agents/tasks/auth-token-implementation.md
Scope: src/auth,tests/auth
ModelProfile: balanced61
Writable: true
Parallel: false
DispatcherRole: main
[/NATIVE_CODEX_AGENT_TASK]
```

Use `prepare-spawn` to generate the envelope and host-compatible payload.
Retain `fork_turns: "none"` or legacy `fork_context: false`, model and effort.
Spawn the ready wave before waiting. While it runs, main stays in its reserved
scope; consume whichever result completes first and recompute readiness.

## Evidence boundary

Original local transcripts verify child identity, terminal state, final report,
model and effort. Missing evidence is a blocker, not permission to invent it.
Without close_agent, record terminal evidence and closeStatus=unsupported.
Child-session provenance and host tool isolation help prevent nested dispatch;
they do not authenticate a hostile process with the same local file privileges.
Whole-workflow acceptance belongs to main. Final-verifier workers call
`verify-final-inputs`, never their own whole-workflow acceptance.
