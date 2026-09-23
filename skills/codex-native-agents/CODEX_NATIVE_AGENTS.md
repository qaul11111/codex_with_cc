# Codex Native Agents

The main thread owns dispatch, architecture, task boundaries, review, acceptance
and delivery. Workers cannot call `spawn_agent` recursively.

This skill permits main to select direct or delegated execution within authorized
development scope. User restrictions and host policy take precedence. Ordinary
short or coupled tasks stay in main without workflow overhead.

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
- With close_agent, keep original successful close tool evidence. Without it,
  original terminal events prove execution stopped, and closure is unsupported.
  interrupt_agent is never proof of host closure.
- Standard requires current executed checks and a main-thread review. Strict
  implementation requires spec review, quality review, and final verification.
  Review targets are fixed before execution. Main performs overall acceptance;
  a final worker uses verify-final-inputs.
- Empty workflows, pending tasks, stale source, changed evidence and unfinished
  attempts cannot be accepted. Accepted workflows remain immutable.

## Boundaries

The hook recognizes explicit child-session provenance and uses host tool isolation
as a fallback. Declared scopes are scheduling constraints, not a filesystem
sandbox; main still reviews the actual diff. Checks cover Git tracked and
nonignored files (including deletions and symlinks), excluding ArtifactRoot.
Ignored dependencies, external services and runtime environments need relevant
integration checks. Cost/time estimates are planning inputs, not measured savings.

See [adaptive workflows](references/adaptive-workflows.md) for commands, capability
format, failure handling and report requirements.
