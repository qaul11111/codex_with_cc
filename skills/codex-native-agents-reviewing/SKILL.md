---
name: codex-native-agents-reviewing
description: Review native output against exact task inputs and current source, using main review for standard work and independent exact-run reviews for strict work.
---

# Native Agent Reviewing

Read the assignment, actual diff and verification evidence. Main owns acceptance.
Standard: run relevant checks, inspect scope/correctness, then record-main-review.
Strict: spec and quality reviewers inspect the pinned implementation RunId; a
rerun needs fresh preparation. Return the structured report; main uses record-run.

Do not accept a report merely because it says DONE. Check the claimed verification,
changed files, integration points and residual risk. Failed checks or changed source
invalidate acceptance. Never bind a late old report to a newer implementation.
