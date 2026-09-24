# Codex Native Agents

The main thread owns dispatch, architecture, task boundaries, review, acceptance
and delivery. Workers cannot call `spawn_agent` recursively.

Main first follows the [core assessment rules](SKILL.md#assess-before-substantial-execution):
check the actual multi-agent mode, explain a split or concrete direct-work reason,
and dispatch eligible work. The applicable skill explicitly requests delegation
where the mode allows skill requests. User restrictions and hard host prohibitions
take precedence. Short or coupled tasks stay in main without workflow overhead.

## Invariants

- Native GPT-6 Astra, Sol and Luna; contract.json selects model and effort by
  role/complexity, then filters using the active host's exact capabilities.
  Automatic routes can move to stronger supported profiles and record why.
  Explicit profile choices remain pinned. If no route is supported, return to
  main. Never substitute GPT-5.6 IDs or silently inherit the parent's model.
- New workflows explicitly select standard or strict and record a real host
  capability snapshot. Historical records without policy retain strict semantics;
  they are not automatically promoted to the new evidence model.
- A six-section TaskFile defines Goal, Allowed Scope, Forbidden Actions,
  Acceptance Criteria, Verification, Report Requirements. It is hashed before
  dispatch; a changed task requires a fresh registration.
- `prepare-spawn` reserves a slot, checks dependencies and conflicting access,
  pins review RunId/final snapshot and source inputs, and emits the host payload.
  Preserve fork_turns=none or legacy fork_context=false and the requested route.
- Every attempt records the actual returned agent ID. Record its original host
  final report, model and effort. A new attempt needs the previous terminal
  settlement first; at most two attempts are dispatched per task.
- Automatic failed attempts may escalate once along the explicit profile chain.
  A pinned profile needs explicit replanning; missing inputs or permissions need
  resolution, not escalation. Preserve each attempt's original route and reason.
  NEEDS_CONTEXT/BLOCKED are ineligible. Other retries require a recorded capability
  or quality diagnosis with evidence, bound to the previous run/agent.
- With close_agent, keep original successful close tool evidence. Without it,
  original terminal events prove execution stopped, and closure is unsupported.
  interrupt_agent is never proof of host closure.
- Standard requires current executed checks and a main-thread review. Strict
  implementation requires spec review, quality review, and final verification.
  Review targets are fixed before execution. Main performs overall acceptance;
  a final worker uses verify-final-inputs.
- Empty workflows, pending tasks, stale source, changed evidence and unfinished
  attempts cannot be accepted. Accepted workflows remain immutable.
- Only ordered writers with declared dependencies can share registered scope;
  active read/write conflicts still block dispatch. Ready queries read atomic
  state without a lock, but dispatch mutations recheck admission under lock.
- Slow checks run outside the workflow state lock. A separate per-workflow check
  lock prevents overlapping test commands. Results commit only against the same
  generation, workflow state and source. Pending or unresolved checks prevent
  review/acceptance, and failed checks cannot preserve previous success.

## Boundaries

The hook recognizes explicit child-session provenance and uses host tool isolation
as a fallback. Session and per-prompt context remind main to assess; workers get
execution-only guidance. The hook cannot read the model's reasoning or discover
the current multi-agent mode, and cannot guarantee a dispatch. Mode is interpreted
from current instructions by main; `advise` only evaluates supplied inputs.
Declared scopes are scheduling constraints, not a filesystem
sandbox; main still reviews the actual diff. Checks cover Git tracked and
nonignored files (including deletions and symlinks), excluding ArtifactRoot.
Ignored dependencies, external services and runtime environments need relevant
integration checks. Cost/time estimates are planning inputs, not measured savings.

See [adaptive workflows](references/adaptive-workflows.md) for commands, capability
format, failure handling and report requirements.
