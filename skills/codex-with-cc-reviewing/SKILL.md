---
name: codex-with-cc-reviewing
description: Make focused main acceptance decisions from compact worker cards, targeted diffs and current verification evidence.
---

# Codex with CC Reviewing

Read `../codex-with-cc/references/astra-workflows.md` for acceptance commands.
Start from a brief result card: changed paths, checks, findings/risks and evidence
links. Match it to the original run. Inspect relevant actual changes and supporting
evidence, pulling targeted diffs when needed; do not ingest full logs or repeat
worker exploration. Confidence or report formatting alone never proves correctness.
Main retains judgment over requirement coverage, scope, quality and residual risk.
For `claude-process`, review the process receipt, immutable authorization and
actual PID/start/exit evidence; no Codex child or carrier model exists. Missing or
changed process evidence blocks acceptance just as missing child provenance does.

Standard acceptance belongs to main. DONE_WITH_CONCERNS may be accepted only when
required checks passed and every concern has a disposition, reason and evidence in
DecisionsFile. Preserve original status/report and disclose accepted residual risks.
Missing context, failed checks, interrupted execution and BLOCKED/FAIL cannot be
waived through concern dispositions.

Workers select, execute and repair relevant tests. Main invokes the deterministic
run-checks acceptance gate once, judges relevance/sufficiency, records
record-main-review, then verify-workflow. Ordinary worker logs do not automatically
replace gate evidence.
Reuse evidence only while source/run/dependency bindings remain valid. Do not rerun
unchanged checks just to repeat a worker's result; changed covered inputs/runs,
failures or unresolved risk justify renewed validation. Whole-project snapshots are
the default; scoped snapshots require complete task input/dependency declarations.

Add independent focused review when uncertainty or risk warrants it. Strict requires
current spec/quality reviews and final verification bound to exact implementation
runs. Final workers use verify-final-inputs; main accepts after lifecycle settlement.
Formatting variations accepted by the parser need no model call. Send real defects
to a worker for local correction, and replan repeated failures instead of taking
substantial delegated implementation or diagnosis into main or making identical redispatches.
