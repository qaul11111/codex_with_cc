> Codex integration instructions are in [AI_INSTALL.md](AI_INSTALL.md).

# Codex Native Agents

`codex-native-agents` is a local development plugin for disciplined native Codex child-agent workflows. The main thread owns decomposition, dispatch, review, acceptance, and delivery; child agents receive bounded TaskFiles and return structured reports.

## Development Source

Use the fork at [qaul11111/codex_with_cc](https://github.com/qaul11111/codex_with_cc). This repository is not published to a marketplace. Install it only as a local, user-scoped development plugin using the Codex local plugin flow described in [AI_INSTALL.md](AI_INSTALL.md).

## Workflow

- Use one `WorkflowId` and scoped `TaskId` for each delegated assignment.
- Dispatch native `spawn_agent` calls with `fork_context: false` and the full task envelope.
- Spawn independent tasks before waiting; writable tasks may run together only with disjoint scopes.
- Record structured reports and require spec review, quality review, and final verification for implementation work.
- Close every child and verify the workflow before reporting completion.

The five workflow skills cover planning, dispatching, worker execution, reviewing, and finishing. The machine-readable contract and local verifier live in [skills/codex-native-agents](skills/codex-native-agents).
