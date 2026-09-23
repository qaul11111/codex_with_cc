# Native-only adaptive execution verification

Date: 2026-09-07. Branch: `codex/native-only`; base commit: `08a51d9`.
Development checkout: `/Users/wxl/Documents/DevProject/GPTProject/CodexWithCC-native-only`.
The original `CodexWithCC` checkout remains on its prior branch with its existing changes.

## Behavior

- Main chooses direct work for short, coupled or non-independent tasks; scoped
  native work is appropriate when overlap can offset coordination cost.
- All new routes use gpt-6-astra. Role/complexity selects low, medium, high or
  xhigh. Unsupported routes return to main. One retry can escalate one profile;
  attempts have distinct host task names and prior attempts must be settled.
- Host preflight records native tools, fork parameter, Astra efforts and child
  slots. Ready waves obey dependencies, reader/writer conflicts and main scope.
- Standard uses executed checks and main review. Strict retains independent
  spec/quality reviews and final verification. Targets are pinned at dispatch.
- Empty workflows fail. Actual model/effort and final reports are checked against
  original local host logs. Closing requires actual tool evidence when supported;
  otherwise execution terminal evidence records `closeStatus=unsupported`.
- Stale source, changed task/report/log evidence and failed latest checks cannot
  reuse earlier acceptance. Legacy policy-free workflows retain strict semantics.

## Local validation

- Full pytest suite: **141 passed**. No skipped tests or pytest warnings.
- Includes 25 new adaptive-regression cases: current host fork syntax/conflicting
  inheritance; stale review and final snapshots; empty acceptance; shape-based
  routing; dependency/slot/access admission; main-owned writes; symlink aliases
  and escapes; standard/strict flows; actual effort mismatch; interruption;
  original close receipts; log tampering versus unrelated append; current source;
  check failure invalidation; unique bounded escalation and model fallback refusal.
- Hook JavaScript syntax and git diff whitespace checks passed.
- All six skill validators and plugin package validation passed.
- Tests use isolated offline fixtures. No real child model, provider request or
  production benchmark was invoked. No plugin reinstall, commit or push performed.

## Evidence limits and next live trial

This implementation does not prove a speed or cost improvement. Compare similar
real tasks by end-to-end elapsed time, quality, rework and total token use before
claiming gains. A fresh host trial should test standard independent investigations,
strict implementation/review, interruption and route availability.

Transcript support is local JSONL with readable session metadata, turn context,
terminal event and complete final response. Close evidence supports JSON native
function/custom-tool call results. Opaque or missing required evidence fails closed.
Encrypted task messages are not decrypted; this collector verifies identity and
execution, not a complete cryptographic parent-dispatch chain. Local evidence is
not protection against a process able to rewrite all files as the same user.

Scopes are admission rules, not an OS sandbox. Main must review actual changes.
Git snapshots exclude ignored dependencies and ArtifactRoot; external services and
runtime acceptance still need appropriate integration tests. Keep new artifacts
outside tested source. The deployment and original dirty checkout are untouched.
