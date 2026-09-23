# GPT-6 adaptive routing verification

Date: 2026-09-23. Branch: `codex/gpt6-adaptive-routing`.
Base: `ad849fe`, which preserves the previous Astra-only adaptive implementation
on `codex/native-only`. The baseline suite passed 141 tests before that commit.
The older Claude-routing checkout was not modified by this change.

## Implemented behavior

- Main decides whether work is independent and substantial enough to delegate.
  Long batches of simple work can delegate; short or coupled work stays in main.
- Automatic routing selects Luna low, Sol medium/high or Astra xhigh from role,
  complexity and the exact model/effort pairs in the active host catalog. See the
  [routing matrix](../skills/codex-native-agents/references/adaptive-workflows.md#model-selection).
- Unsupported automatic profiles can move upward, with the preferred route,
  actual selection and reasons preserved. Explicit profiles stay pinned. High-risk
  work and final verification cannot use a lower profile.
- `route` previews decisions without workflow artifacts or model calls. Registration
  rejects an unavailable route without leaving an unfinishable pending task.
- One failure can escalate Luna to Sol or Sol to Astra after terminal settlement;
  each task has at most two attempts. Pins require explicit replanning. Failed
  preparation does not alter the task's selected model or evidence.
- Readiness separates first attempts and eligible escalations while reserving
  scopes and slots across both. A second preparation without explicit escalation
  is rejected, so ordinary retries cannot bypass the top-profile stopping rule.
- Prepared, spawn and run records retain route evidence. Hooks and original host
  transcripts must agree on the exact model and effort. Existing scope, dependency,
  concurrency, lifecycle and standard/strict acceptance checks remain in force.

## Current host observation

The active session's spawn schema on this date advertises `gpt-6-astra`, but
`gpt-5.6-sol` and `gpt-5.6-luna`, not the requested GPT-6 Sol/Luna IDs. The local
model cache was also older (2026-09-15); it was not treated as current capability
evidence and was not modified.

The source CLI was run using a capability file transcribed from the actual active
tool schema. These were decision previews, not model executions:

| Request | Observed result |
| --- | --- |
| researcher / simple / automatic | Prefers economy; selects supported Astra xhigh and explains missing GPT-6 Luna/Sol |
| implementer / normal / automatic | Prefers balanced; selects supported Astra xhigh and explains missing GPT-6 Sol |
| implementer / fixed balanced | No model; returns main_thread because the exact GPT-6 Sol route is unavailable |

No GPT-5.6 model was substituted, no GPT-6 Sol/Luna execution was attempted, and no speed or cost
savings were measured. New model availability must be checked in the actual host
session used for dispatch. This source branch has not replaced the installed plugin.

## Validation

Final source regression: **226 passed in 8.93s**, using Python 3.13 with
`PYTHONNOUSERSITE=1 python3 -m pytest -q`. Plugin validation, all six skill
validators, JSON parsing, Node syntax checking and `git diff --check` passed.

The behavior tests cover routing, host capabilities, model pins, escalation,
atomic failure, preserved attempt evidence and existing acceptance safeguards.
Hook tests check every configured model/effort pair and reject older model IDs.
Skill and plugin validators check the updated package. An independent read-only
skill exercise covered a concurrent page/log task and an unavailable explicit Sol
restriction; the guide now includes the complexity matrix and log-scan example.
An independent reviewer also exercised successful standard and strict fixture
workflows with different model tiers and found a same-tier retry bypass; it was
fixed and included in the final regression. All of these are offline fixtures.

## Official sources checked

- [OpenAI model catalog](https://developers.openai.com/api/docs/models): exact
  GPT-6 Astra/Sol/Luna model IDs, intended workloads, and listed standard input/output
  prices of $10/$50, $2/$10, and $0.1/$0.5 per million tokens respectively.
- [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents):
  per-agent model and reasoning configuration, inherited defaults, and token overhead.

Prices are a dated reference, not a billing estimate. The implemented policy does
not learn from historical latency or token usage, switch the main-session model,
or run an autonomous background scheduler. Real workload comparison and fresh-host
execution remain separate from source validation.
