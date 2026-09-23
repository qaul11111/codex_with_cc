# Adaptive native workflows

Use the installed native_agents.py for real dispatch; source scripts are for
local development. Main works directly when useful independent work is absent.
`advise` is a deterministic planning aid, not a model or an automatic launcher:

```sh
python3 skills/codex-native-agents/scripts/native_agents.py advise --complexity complex --independent --estimated-minutes 20 --overhead-minutes 2
```

Estimates are supplied by main. Consider coupling and integration cost, not just
file count. Read-only investigations can overlap; readers cannot inspect a file
while a scheduled writer changes it. Reserve shared integration files for main.

## Preflight and initialization

Read the actual active tool schema and save its capability snapshot. This example
is a schema example, not evidence of the current host. maxAgents means available
child slots, excluding main. Use the exact host fork parameter, model IDs and efforts.

```json
{"source":"active-tool-catalog","tools":["spawn_agent","list_agents","wait_agent"],"forkParameter":"fork_turns","models":{"gpt-6-luna":["low","medium","high"],"gpt-6-sol":["low","medium","high","xhigh"],"gpt-6-astra":["low","medium","high","xhigh"]},"maxAgents":3}
```

```sh
python3 skills/codex-native-agents/scripts/native_agents.py init --workflow-id <id> --profile standard --project-root <absolute-project> --artifact-root <absolute-artifacts> --host-capabilities <caps.json> --main-scope <integration-path>
```

Use strict for high risk or requested independent reviews. Policy is fixed at
initialization. Never edit workflow JSON to bypass admission or acceptance.
Capabilities describe this host; do not copy a different host's snapshot.
API model availability or a model picker entry does not prove that this session's
spawn tool supports the model. In particular, gpt-5.6-sol/luna are not aliases for
gpt-6-sol/luna. A new session may expose a newer catalog; inspect it again.

## Model selection

Preview a route without creating workflow artifacts or starting a model:

```sh
python3 skills/codex-native-agents/scripts/native_agents.py route --role implementer --complexity normal --host-capabilities <caps.json>
```

The four profiles are economy (Luna low), balanced (Sol medium), balancedHigh
(Sol high), and frontier (Astra xhigh). Role and complexity choose a preferred
profile. Automatic selection tries that profile, then stronger supported profiles;
the result includes the preferred profile, actual route and reason. Never choose
a lower profile to bypass missing capability. If nothing qualifies, return to main.
Registration rejects an unavailable route before creating a pending task, so other
tasks can still finish. Respect user model restrictions when choosing any main-thread
follow-up; a fallback is not permission to run restricted work on a different model.

`--complexity` accepts simple, normal (default), complex and high-risk:

| Role | simple | normal | complex | high-risk |
| --- | --- | --- | --- | --- |
| researcher | economy | balanced | balancedHigh | frontier |
| implementer | balanced | balanced | balancedHigh | frontier |
| planner | balanced | balanced | frontier | frontier |
| reviewer | balanced | balancedHigh | frontier | frontier |
| final-verifier | frontier | frontier | frontier | frontier |

A focused independent log scan can use `--role researcher --complexity simple`
to choose Luna automatically, keeping failure escalation available. Do not add an
economy pin merely to trigger Luna. A complex investigation tracing unknown
causes deserves complex instead. Short scans still stay in main when dispatch
overhead exceeds useful work; a long batch of simple scans can benefit from delegation.

Use `--model-profile <profile>` for a user's explicit choice. A pin cannot change
on capability failure or retry. High-risk tasks and final verification require
frontier; explain an incompatible lower pin instead of silently overriding it.
The same choice must be supplied at registration. Main-session model switching
is outside this workflow. Pricing and measured latency are not inputs to this
deterministic router; compare real tasks before claiming savings.

## Register and dispatch

TaskFiles have Goal, Allowed Scope, Forbidden Actions, Acceptance Criteria,
Verification and Report Requirements. Reports have Status, Role, Summary,
Changed Files, Verification, Findings, Final Result and Risks Or Follow-ups.
Status and Final Result match: DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, BLOCKED or
FAIL. Only DONE can be accepted. Include actual check commands and outcomes.

```sh
python3 skills/codex-native-agents/scripts/native_agents.py validate-task --task-file <task.md> --role implementer
python3 skills/codex-native-agents/scripts/native_agents.py register-task --workflow-id <id> --task-id <task> --role implementer --task-file <task.md> --scope src/module --writable --parallel --complexity normal --depends-on <previous-task>
python3 skills/codex-native-agents/scripts/native_agents.py ready --workflow-id <id>
python3 skills/codex-native-agents/scripts/native_agents.py prepare-spawn --workflow-id <id> --task-id <task>
```

All commands accept --artifact-root; use the same absolute path throughout.
Omit --depends-on when independent and --parallel when serial. Dependencies must
already be registered. Omit --model-profile for automatic selection; a supplied
profile is pinned and must meet the task's risk requirements. Scope includes relevant reads as well as writes; broad scopes
trade parallelism for safety. Reviewers/final-verifiers must be read-only.

Call the actual native spawn tool using the emitted payload. Do not reconstruct
its fork/model/effort fields. Immediately register the returned ID:

```sh
python3 skills/codex-native-agents/scripts/native_agents.py record-spawn --workflow-id <id> --task-id <task> --agent-id <actual-id> --actual-model <prepared-model>
```

Prepare and spawn every eligible task in a ready wave before waiting. Continue
non-conflicting main work. When results arrive, record/settle them and recompute
ready tasks. Do not launch future dependency waves early. Cap concurrency by host
slots and useful independent work. Do not start a child solely to occupy a slot.
`ready` separates first attempts in `ready` from eligible retries in
`requiresEscalation`; both share the same scope and slot reservations. Review the
failure cause before preparing a retry with `--escalate`. `blocked` explains pins,
exhausted routes, dependencies or capacity. A second ordinary preparation is rejected.

A failed or interrupted first automatic attempt may use prepare-spawn --escalate:
economy moves to balanced, balanced/balancedHigh move to frontier. Capability
selection can skip unsupported intermediate profiles upward. Frontier has no
higher route. A pin requires explicit replanning instead of escalation. A second
failure returns to main for diagnosis/replanning. Missing inputs require
clarification, not more effort. Preserve each attempt's original model/effort/reason.
If a spawn fails or its outcome is uncertain, preserve the prepared record and
resolve the actual host state before retrying. Never clear a reservation to hide
an unrecorded child. An unresolved preparation blocks acceptance.

## Original host evidence and lifecycle

```sh
python3 skills/codex-native-agents/scripts/native_agents.py record-run --workflow-id <id> --task-id <task> --agent-id <actual-id> --report-file <report.md> --transcript-path <original-child.jsonl>
python3 skills/codex-native-agents/scripts/native_agents.py record-close --workflow-id <id> --task-id <task> --agent-id <actual-id> --status unsupported --transcript-path <original-child.jsonl>
```

Use original CODEX_HOME/sessions logs, never a transcript written by an agent.
The final response must match the report. New runs verify model and effort from
turn_context; missing or incompatible host formats fail closed. These records
bind identity and execution; they do not decrypt encrypted task messages.

When capabilities contain close_agent, call it after the terminal event and use
--status closed --close-transcript <original-parent.jsonl>. The collector supports
JSON function/custom tool call/result records; opaque close receipts are unsupported.
When close_agent is absent, use unsupported and retain verified terminal evidence.
A child interrupted before returning a report can be settled without record-run;
its missing completion cannot be turned into DONE. Preserve all earlier attempts.
If logs are missing or opaque, stop dispatch before adding more unresolved work.

## Standard acceptance

Put checks/review files under ArtifactRoot, outside the tested source snapshot.
Checks use explicit argv (not shell interpolation):

```json
{"checks":[{"argv":["python3","-m","pytest","-q"],"cwd":".","timeoutSeconds":300}]}
```

```sh
python3 skills/codex-native-agents/scripts/native_agents.py run-checks --workflow-id <id> --checks-file <checks.json>
python3 skills/codex-native-agents/scripts/native_agents.py record-main-review --workflow-id <id> --review-file <review.md>
python3 skills/codex-native-agents/scripts/native_agents.py verify --workflow-id <id>
```

Main review explains scope compliance, correctness and remaining risks; check
sufficiency still requires judgement. A failed check invalidates earlier evidence.
Source/run changes require new checks/review. No independent reviewers are required
for standard; add them when useful rather than mechanically for every small edit.

## Strict acceptance

After an implementation finishes and is settled, register separate spec and
quality reviewers with --review-for-task-id <impl> --review-kind spec|quality.
prepare-spawn pins the current implementation RunId; late old reports are rejected.
After both reviews are current, prepare the final-verifier. It invokes
verify-final-inputs --workflow-id <id> --task-id <final> before its verification.
The final snapshot is fixed before execution. Main settles the final worker and
runs verify. Source changes after review/final preparation invalidate those inputs.

Legacy records retain legacy strict validation. Start a fresh workflow to use
capability-bound lifecycle, actual model/effort evidence and standard acceptance.
