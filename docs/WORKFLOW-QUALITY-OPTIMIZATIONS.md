# Workflow optimizations with preserved acceptance checks

Date: 2026-09-24. Source branch: `codex/gpt6-adaptive-routing`.
Baseline: `0ffc9b0`, installed as `0.1.0+codex.20260923070822` before this update.

## Behavior

1. `NEEDS_CONTEXT` and `BLOCKED` cannot enter a stronger-model retry. A completed
   attempt without its verified report also cannot bypass that rule. A real
   failure, concerns report or verified interruption remains eligible for at most
   one stronger supported route, with a required capability/quality diagnosis and
   supporting observations. The diagnosis records the previous run and agent.
   Explicit pins, high-risk routing and the two-attempt limit are preserved.
2. Writers with overlapping scopes may register as parallel-capable when the
   later writer explicitly depends, directly or transitively, on the earlier one.
   They still execute in order after success and terminal settlement, while
   unrelated work can proceed. Sibling writers, active readers/writers, host slots
   and main-reserved scopes retain their existing conflict checks.
3. `ready` reads atomically replaced workflow state without waiting for a lock.
   Preparation and spawn recording still recheck current admission under the
   workflow lock. Slow checks run outside the workflow state lock, with short
   locked transactions for invalidation and commit. A separate check lock permits
   only one verification execution per workflow, preserving isolation from
   overlapping test commands. A duplicate request fails promptly without
   modifying the active check's state.

Check results commit only when generation, workflow state and source still match.
Concurrent registration or run/policy changes cause old checks to be rejected.
Pending/unresolved checks block main review and both acceptance profiles. Failed,
timed-out or cancelled checks persist a failure blocker for both profiles and
cannot retain partial success or an old main review. This also blocks strict
acceptance when extra checks fail after earlier valid independent reviews.
SIGTERM unwinds and stops the owned check subprocess. On POSIX, check commands
inherit the execution lock: a surviving command retaining its descriptor blocks
recovery after CLI SIGKILL. The unresolved marker blocks acceptance until fresh
checks complete. Commands must stay in the foreground and preserve inherited
descriptors; detached descendants, tools closing those descriptors and Windows
require confirmation that old processes have stopped before recovery.

## Regression evidence

The source suite passed **295 tests** in 17.52 seconds, retaining the previous
264 cases and adding 31 behavioral cases. Existing successful retry tests now
provide the newly required diagnosis. No model routing tiers or acceptance checks
were removed. Plugin validation, both changed skill validators and diff whitespace
checks passed.

New cases cover:

- Context/blocker status rejection without consuming a slot; missing report
  rejection; diagnosed quality retry and preserved earlier-run references.
- Direct/transitive dependent writers overlapping unrelated work; successful
  report plus terminal settlement required; sibling writers and active readers
  rejected; stale ready advice cannot authorize dispatch.
- Ready queries and unrelated registrations during a barrier-controlled check;
  workflow/source changes rejected both during checks and just before commit.
- Duplicate check requests, late generations, partial-success check lists,
  nonzero exit, timeout, missing command, SIGTERM cleanup, SIGKILL unresolved
  state and rejection of recovery while the original check survives; pending and
  failed extra checks rejected in standard and strict acceptance, followed by
  successful recovery only after full fresh checks.

An independent Sol medium worker designed 12 adversarial acceptance scenarios
using only an immutable baseline. A separate Sol high review inspects the frozen
candidate source; its result is recorded separately from the regression suite.

## Local latency comparison

Five baseline and five candidate runs used the same local fixture: one actual
check command waits 1.2 seconds, and another CLI process requests `ready` after
the check signals it has started. Completion markers and successful check
evidence confirm the check ran fully in every sample.

| Measurement | Baseline median / maximum | Candidate median / maximum |
| --- | --- | --- |
| Ready response | 1264.60 / 1298.07 ms | 49.81 / 50.62 ms |
| Full check command lifecycle | 1331.60 / 1336.68 ms | 1342.31 / 1349.42 ms |
| Ready completed before check | 0 of 5 | 5 of 5 |

The candidate removes the query's wait behind the check. Extra state/source
verification adds about 11 ms to this small fixture's full check lifecycle. This
is a local concurrency result, not a claim of zero overhead or measured speedup
across model-backed development tasks. Validation strength takes priority over
removing those checks. Actual model latency, task quality and large-project
performance still require comparable real workloads.

Raw local evidence is under `.codex/speed-quality-20260924/` in the original
project checkout (ignored), including `latency-comparison-final.json`, the independent
reports, frozen source mirrors and their manifest. No other active task was
interrupted or reconfigured, and the older dirty checkout's source was preserved.
