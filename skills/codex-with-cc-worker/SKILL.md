---
name: codex-with-cc-worker
description: Prepare bounded end-to-end worker tasks and compact evidence-backed result cards for Claude Code or native Codex execution.
---

# Codex with CC Worker

Read `../codex-with-cc/references/astra-workflows.md` for prepared routes and
acceptance. Read `../codex-with-cc/CODEX_WITH_CC.md` only for legacy/session details.
Native workers execute directly and return a structured final message for original
host-log collection. Legacy Claude carriers launch and relay; Claude workers execute.
`claude-process` workers run outside Codex without a model carrier or child-thread
identity. Use only the prepared task's authorized commands; changed authorization
or pinned inputs needs a fresh main-owned plan, not a blanket shell bypass.
Workers never approve their own workflow; acceptance belongs to main.

Task files retain these exact sections, with detail proportional to the assignment:

- `Goal`: one coherent outcome and intended role.
- `Allowed Scope`: permitted writes and relevant reads.
- `Forbidden Actions`: excluded behavior, files, nested delegation and follow-up work.
- `Acceptance Criteria`: observable completion criteria.
- `Verification`: exact required commands or the smallest meaningful checks to select.
- `Report Requirements`: Status, Role, Summary, Changed Files, Verification, Findings, Final Result, Risks Or Follow-ups.

An implementer owns exploration, implementation, test execution and local repair
within that assignment. Keep those activities together for delegated
changes; main may handle simple known-location low-risk tasks directly. Do not ask
main to perform routine diagnosis or choose local implementation details. If required intent or authority is missing, stop before
affected edits and report `NEEDS_CONTEXT`; routine discoverable facts belong to
worker investigation. Execute directly without nested delegate runs or scope growth.

Use verification appropriate to behavior and risk; test-first or the smallest
equivalent verification-first evidence is useful when a practical test surface
exists. Do not add mirrored tests for trivial reversible edits. Preserve commands,
outputs and source/run bindings. After relevant checks pass, repeat them only when
new changes, failures or unresolved concerns justify it.

Reviewers perform one assigned kind, `spec` or `quality`, for the pinned target run.
They independently inspect actual code, artifacts, scope and relevant evidence.
Final verifiers read `../codex-with-cc/references/lifecycle.md`, run
`verify-final-inputs`, and independently verify content/check sufficiency. They do
not demand self-dependent workflow acceptance or claim their own thread is closed.

Return all eight fields as a brief result card: outcome, changed paths, checks and
results, findings/risks, and concrete artifact links. Keep noisy logs and extended
analysis in artifacts; do not paste them into main. Before reporting, check scope,
changed files, evidence and residual risks. Use `DONE_WITH_CONCERNS` only after
required verification passed; `NEEDS_CONTEXT` for a necessary main decision,
`BLOCKED` for external blockers and `FAIL` for failed work or invalid verification.
