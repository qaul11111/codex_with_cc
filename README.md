> Codex integration instructions are in [AI_INSTALL.md](AI_INSTALL.md).

# Codex Native Agents

`codex-native-agents` is a local development plugin for disciplined native Codex child-agent workflows. The main thread owns decomposition, dispatch, review, acceptance, and delivery; child agents receive bounded TaskFiles and return structured reports.

## Development Source

Use the fork at [qaul11111/codex_with_cc](https://github.com/qaul11111/codex_with_cc). This repository is not published to a marketplace. Install it only as a local, user-scoped development plugin using the Codex local plugin flow described in [AI_INSTALL.md](AI_INSTALL.md).

## Adaptive execution

Main selects direct execution for short or coupled work, or native Astra workers
for useful independent tasks. Profiles vary reasoning effort, not model family.
Read/write conflicts, dependencies and host slots govern parallel task waves.
Standard uses executed checks and main review; strict uses exact-run independent
reviews and final verification. Original local host logs verify execution and
lifecycle; hosts without close_agent use terminal evidence with unsupported closure.

See [Chinese usage](docs/README.zh-CN.md) and the
[command guide](skills/codex-native-agents/references/adaptive-workflows.md).
