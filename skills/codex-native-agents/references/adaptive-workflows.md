# Adaptive native workflows

Use the installed native_agents.py for real dispatch; source scripts are for
local development. Main works directly when useful independent work is absent.
`advise` is a deterministic planning aid, not a model or an automatic launcher:

```sh
python3 skills/codex-native-agents/scripts/native_agents.py advise --complexity complex --independent --main-work-available --estimated-minutes 20 --overhead-minutes 2 --multi-agent-mode explicit-only --delegation-request skill
```

Main supplies the mode from current host instructions: `enabled` permits proactive
delegation; `explicit-only` requires an explicit `user`, `agents` (AGENTS.md), or
applicable `skill` request; `disabled` prohibits it. This core skill explicitly
requests eligible delegation, so use `skill` when applicable. Do not use it to
override a hard prohibition. Unknown mode defaults to `unknown` and recommends
main until resolved. `--user-restriction no-agents|serial` takes precedence.
`--main-work-available` means useful non-conflicting main work actually exists.
The command returns concrete `reasonCodes` and `nextAction`, creates no workflow,
and neither discovers mode nor authorizes dispatch. Native advice still requires
the capability and scope preflight below; report actual unavailable-model/tool or
admission blockers rather than claiming a worker ran. Reassess if inputs change.

Estimates are supplied by main. Consider coupling and integration cost, not just
file count. Read-only investigations can overlap; readers cannot inspect a file
while a scheduled writer changes it. Reserve shared integration files for main.

## Preflight and initialization

Read the actual active tool schema and save its capability snapshot. This example
is a schema example, not evidence of the current host. maxAgents means available
child slots, excluding main. Use the exact host fork parameter, model IDs and efforts.

```json
{"source":"active-tool-catalog","tools":["spawn_agent","send_input","resume_agent","wait_agent","close_agent"],"forkParameter":"fork_context","models":{"gpt-6-luna":["low","medium","high"],"gpt-6.1-sol":["low","medium","high","xhigh","max"],"gpt-6-astra":["low","medium","high","xhigh"]},"maxAgents":1}
```

```sh
python3 skills/codex-native-agents/scripts/native_agents.py init --workflow-id <id> --profile standard --project-root <absolute-project> --artifact-root <absolute-artifacts> --host-capabilities <caps.json> --main-scope <integration-path>
```

`spawn_agent` and `wait_agent` (or legacy `wait`) are required. `list_agents` is
optional discovery, not a dispatch prerequisite. Without it, track only agent IDs
returned by your own spawns, wait on those IDs, and retain the original transcript
and actual close receipts. Do not fabricate discovery results or replace native
agent discovery with a chat-listing API. Workflow concurrency limits cover registered
workers, not an inventory of other chats; use a conservative available-slot budget
and treat a host admission rejection as a blocker, never evidence of a user ban.
If initialization fails, stop: do not run registration or preparation against a
nonexistent workflow. Correct the reported capability problem or return to main.

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

The active profiles are economy (Luna low), balanced61 (6.1 Sol medium),
balancedHigh61 (6.1 Sol high), deliberate61 (6.1 Sol xhigh), and frontier
(Astra xhigh). Legacy balanced/balancedHigh retain GPT-6 Sol medium/high for
existing records and explicit pins; new automatic routes do not fall back to
old Sol. Role, complexity and risk choose a preferred profile. Automatic selection tries that profile, then stronger supported profiles;
the result includes the preferred profile, actual route and reason. Never choose
a lower profile to bypass missing capability. If nothing qualifies, return to main.
Registration rejects an unavailable route before creating a pending task, so other
tasks can still finish. Respect user model restrictions when choosing any main-thread
follow-up; a fallback is not permission to run restricted work on a different model.

`--complexity` accepts simple, normal (default), complex and legacy high-risk.
`--risk normal|high` is independent of complexity. High risk always requires a
strict workflow and frontier; legacy complexity high-risk has the same effect
even with `--risk normal`. Use high risk for consequential security/privacy,
irreversible data changes, financial decisions or similarly uncertain impact.
Complex but testable work with ordinary impact may stay standard and use Sol.
This matrix shows normal risk except the high-risk column:

| Role | simple | normal | complex | high-risk |
| --- | --- | --- | --- | --- |
| researcher | economy | balanced61 | balancedHigh61 | frontier |
| implementer | balanced61 | balanced61 | balancedHigh61 | frontier |
| planner | balanced61 | balanced61 | deliberate61 | frontier |
| reviewer | balanced61 | balancedHigh61 | deliberate61 | frontier |
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
Overlapping writers may both use --parallel if the later task has a direct or
transitive dependency on the earlier writer. They execute sequentially after
successful terminal settlement while remaining eligible to overlap unrelated
work. A common ancestor is not an ordering between sibling writers. Readers
still cannot overlap an active writer, and main-reserved scopes remain blocked.

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
`ready` reads an atomically replaced state file without waiting for the workflow
lock. Its suggestions reserve nothing; prepare-spawn and record-spawn recheck the
current state under the lock before admission.

A failed or interrupted first automatic attempt may use prepare-spawn --escalate:
economy moves to balanced61; balanced61/balancedHigh61/deliberate61 move
directly to frontier. Legacy balanced/balancedHigh also move to frontier.
There is no medium-to-high-to-xhigh retry ladder: every task still has at most
two attempts. Capability
selection can skip unsupported intermediate profiles upward. Frontier has no
higher route. A pin requires explicit replanning instead of escalation. A second
failure returns to main for diagnosis/replanning. Missing inputs require
clarification, not more effort. Preserve each attempt's original model/effort/reason.
`NEEDS_CONTEXT` and `BLOCKED` are excluded from escalation by the runtime. Resolve
the blocker in main; if task inputs/scope must change, register a fresh corrected
task/workflow and preserve the original failed records. Do not edit a pinned
TaskFile or clear a failed status to force acceptance. For other failures or a
verified interruption, main must explain why a stronger model addresses the
observed problem:

```sh
python3 skills/codex-native-agents/scripts/native_agents.py prepare-spawn --workflow-id <id> --task-id <task> --escalate --escalation-cause quality --escalation-note "Original report failed the required boundary cases; inputs and tools were available."
```

Use capability or quality as the cause, with supporting observations. The runtime
records the diagnosis and previous run/agent; it cannot determine whether the
explanation is true. A FAIL status or interruption is not itself sufficient proof
of inadequate model capability. A completed attempt without its verified report
cannot bypass the status check by recording only terminal settlement.
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

`run-checks` uses short workflow locks to invalidate old results, pin state and
commit current results. Test commands run outside that lock, so queries and other
workflow operations can proceed. A separate check lock permits only one check
execution per workflow; a concurrent second request fails promptly without
changing the first one's evidence. Wait for the active check or resolve its state
before retrying; do not delete lock files.

Source/workflow changes during checks cause rejection at commit, including new
tasks, reservations, runs or policy changes. Pending/unresolved checks block main
review and both acceptance profiles. Failed/cancelled runs persist a failure
record, so an earlier strict final verification cannot override a failed extra
check. A full fresh successful check run clears that blocker. SIGTERM and normal
exceptions clean up the owned check process and partial evidence. On POSIX, the
check command inherits the execution lock: a surviving command retaining that
descriptor blocks recovery after the CLI is SIGKILLed. The unresolved marker
also blocks acceptance until fresh checks succeed. Use foreground commands that
preserve inherited descriptors; detached descendants, descriptor-closing tools
and Windows need confirmation that old processes have stopped before recovery.
Do not delete lock files or manually clear failure/pending records.

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
