> Codex integration instructions are in [AI_INSTALL.md](AI_INSTALL.md).

# Codex Native Agents

`codex-native-agents` is a local development plugin for disciplined native Codex child-agent workflows. The main thread owns decomposition, dispatch, review, acceptance, and delivery; child agents receive bounded TaskFiles and return structured reports.

## Development Source

Use the fork at [qaul11111/codex_with_cc](https://github.com/qaul11111/codex_with_cc). This repository is not published to a marketplace. Install it only as a local, user-scoped development plugin using the Codex local plugin flow described in [AI_INSTALL.md](AI_INSTALL.md).

## Adaptive execution

Before substantial work, main assesses the current multi-agent mode, useful
independent tasks and coordination cost, then states a split or concrete reason
to work directly. Eligible work must be dispatched after preflight. The skill
explicitly requests delegation where host mode permits skill requests, while
preserving hard prohibitions and user limits. Per-prompt reminders also cover
ordinary development requests; they are instructions, not a guaranteed scheduler.
Routing balances GPT-6 Luna for focused work,
GPT-6.1 Sol for ordinary and complex verifiable implementation/analysis, and
GPT-6 Astra for high-risk judgement, diagnosed escalation and strict final verification.
Risk is independent of complexity (`--risk high`); ordinary completion keeps
standard checks and main review. Legacy GPT-6 Sol profiles remain fixed for
pending tasks and explicit pins.
The active host's exact model IDs and reasoning efforts constrain every route.
Unavailable automatic routes may select a stronger supported profile; explicit
profile choices stay pinned. No GPT-5.6 alias substitution is allowed.
Read/write conflicts, dependencies and host slots govern parallel task waves.
Standard uses executed checks and main review; strict uses exact-run independent
reviews and final verification. Original local host logs verify execution and
lifecycle; hosts without close_agent use terminal evidence with unsupported closure.

See [Chinese usage](docs/README.zh-CN.md) and the
[command guide](skills/codex-native-agents/references/adaptive-workflows.md).
Use the guide's `route` command to preview a decision without starting a worker.
This is task- and capability-based routing, not a learned cost optimizer; measured
speed, quality and total cost still require comparable real workloads.
