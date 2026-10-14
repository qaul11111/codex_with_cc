---
name: codex-with-cc-planning
description: Plan scoped end-to-end worker assignments while main retains requirements, routing decisions and focused acceptance.
---

# Codex with CC Planning

Read `../codex-with-cc/references/astra-workflows.md` for commands. Main clarifies
requirements, sets boundaries and acceptance, and chooses backend/model/effort.
Main may directly finish simple, known-location, low-risk small tasks. Substantial
exploration, implementation, tests and repair belong to workers. Exploration-heavy
or coupled substantial work goes to one end-to-end worker. Optional `advise-task`
estimates inform granularity and routing; they do not override main judgment or an
explicit user choice. Do not use fixed line/file/duration routing thresholds.

Give each worker a coherent outcome and sufficient authority to finish it. Avoid
micro-delegation and mandatory discovery/implementation/test handoffs. Keep the six
TaskFile fields concise, with exact allowed writes, relevant reads, constraints and
meaningful checks. Workers resolve routine implementation choices within scope;
escalate only missing intent, conflicting requirements or scope changes.

Record real dependencies with `DependsOn`; parallelize only independent scopes.
Set MaxParallel from actual host capacity. Main write reservations exist for
explicitly authorized coordination artifacts, not for taking over substantial
delegated coding.
Do not create workers merely to fill slots. Ready chosen tasks use
`prepare-task -Admit`; queue discovery and advice are optional when they inform
a real decision. Reviewers pin the exact target run.

Use standard main acceptance by default and independent focused review when useful.
Use strict for required or warranted independent spec/quality/final review. Preserve
current Claude provider routing; native is available only when user routing permits.
Prefer supported `claude-process` for Claude work, with task-specific exact command
authorization and a bounded execution timeout. It has no Codex carrier model;
plan process lifecycle separately from native/legacy child closure. Legacy
`claude-code` remains available where needed; unsupported routes return to main.
Record override reasons and check host support. Declare input coverage complete
only when shared code, build configuration and dependencies are included; otherwise
retain whole-project checks. Use validate-task for generated files.

Plan a brief result card with changed paths, checks, risks and evidence links, so
main need not ingest repository dumps or full report relays. Reuse current verified
evidence, and recheck only when changes, failures or unresolved concerns justify it.
