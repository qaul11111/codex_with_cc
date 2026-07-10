---
name: codex-native-agents-dispatching
description: Dispatch native Codex child agents with validated task envelopes, model routing, parallel-scope safety, reports, reviews, closure, and workflow verification.
---

# Native Agent Dispatching

Read `../codex-native-agents/CODEX_NATIVE_AGENTS.md` and use only the native tools. The main thread owns every dispatch; workers must never create nested agents.

1. Validate the TaskFile.
2. Initialize and register the workflow task with `native_agents.py`.
3. For independent work, spawn every eligible task before waiting for any result.
4. Call `spawn_agent` with `fork_context: false` and the full native task envelope; record the agent ID, requested model profile, and any inheritance fallback.
5. Continue only non-overlapping main-thread work while children run.
6. Wait only when the critical path needs a result, then record the structured report.
7. For implementers, run separate spec review, quality review, and final verification; record each result.
8. Close every completed, failed, or interrupted agent, then verify the workflow.

Do not parallelize writable tasks with overlapping scope. A blocked or rejected result returns control to the main thread for bounded rework or escalation.
