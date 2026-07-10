---
name: codex-native-agents-dispatching
description: Dispatch native Codex child agents with validated task envelopes, model routing, parallel-scope safety, reports, reviews, closure, and workflow verification.
---

# Native Agent Dispatching

Read `../codex-native-agents/CODEX_NATIVE_AGENTS.md` and use only the native tools. The main thread owns every dispatch; workers must never create nested agents.

Use `skills/codex-native-agents/scripts/native_agents.py`. For each task:

```bash
python3 skills/codex-native-agents/scripts/native_agents.py validate-task --task-file <task.md> --role <role>
python3 skills/codex-native-agents/scripts/native_agents.py init --workflow-id <workflow-id>
python3 skills/codex-native-agents/scripts/native_agents.py register-task --workflow-id <workflow-id> --task-id <task-id> --role <role> --task-file <task.md> --scope <path> --model-profile <profile> --writable [--parallel]
# Reviewer registration additionally requires:
python3 skills/codex-native-agents/scripts/native_agents.py register-task --workflow-id <workflow-id> --task-id <review-id> --role reviewer --task-file <review.md> --scope <path> --model-profile balancedHigh --review-for-task-id <implementer-id> --review-kind spec
```

1. Validate the TaskFile.
2. Initialize and register the workflow task with `native_agents.py`.
3. For independent work, spawn every eligible task before waiting for any result.
4. Call `spawn_agent` with `fork_context: false` and the full native task envelope. Immediately record the returned agent ID and the observed route: `python3 skills/codex-native-agents/scripts/native_agents.py record-spawn --workflow-id <workflow-id> --task-id <task-id> --agent-id <agent-id> --actual-model <host-model>`, or use `--inherit-parent --fallback-reason <reason>` when the host falls back. A different actual model also requires `--fallback-reason`.
5. Continue only non-overlapping main-thread work while children run.
6. Wait only when the critical path needs a result, then record the structured report: `python3 skills/codex-native-agents/scripts/native_agents.py record-run --workflow-id <workflow-id> --task-id <task-id> --agent-id <agent-id> --report-file <report.md>`. `record-run` requires matching spawn evidence for the same agent ID.
7. For implementers, register and run separate `spec` and `quality` reviewers plus a `final-verifier`; record each with `record-run` after its report is returned.
8. Close every completed, failed, or interrupted agent, then run `python3 skills/codex-native-agents/scripts/native_agents.py verify --workflow-id <workflow-id>`.

Do not parallelize writable tasks with overlapping scope. A blocked or rejected result returns control to the main thread for bounded rework or escalation.
