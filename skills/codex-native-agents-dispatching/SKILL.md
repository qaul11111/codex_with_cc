---
name: codex-native-agents-dispatching
description: Dispatch eligible native Astra task waves with capability preflight, exact task metadata, independent scopes and original host evidence.
---

# Native Agent Dispatching

Read ../codex-native-agents/references/adaptive-workflows.md for command arguments.
Use the actual host tool catalog and preserve the emitted payload. Only main
spawns agents. Spawn the ready wave before waiting; process whichever finishes
first, then recompute readiness. Main continues only in non-conflicting scope.

Command sequence (all support the same --artifact-root where applicable):

```sh
python3 skills/codex-native-agents/scripts/native_agents.py init --workflow-id <id> --profile standard --host-capabilities <caps.json> --project-root <project>
python3 skills/codex-native-agents/scripts/native_agents.py validate-task --task-file <task.md> --role implementer
python3 skills/codex-native-agents/scripts/native_agents.py register-task --workflow-id <id> --task-id <task> --role implementer --task-file <task.md> --scope <path> --model-profile balanced --writable --parallel
python3 skills/codex-native-agents/scripts/native_agents.py ready --workflow-id <id>
python3 skills/codex-native-agents/scripts/native_agents.py prepare-spawn --workflow-id <id> --task-id <task>
python3 skills/codex-native-agents/scripts/native_agents.py record-spawn --workflow-id <id> --task-id <task> --agent-id <actual-id> --actual-model gpt-6-astra
python3 skills/codex-native-agents/scripts/native_agents.py record-run --workflow-id <id> --task-id <task> --agent-id <actual-id> --report-file <report.md> --transcript-path <original-child.jsonl>
python3 skills/codex-native-agents/scripts/native_agents.py verify --workflow-id <id>
```

record-run requires matching spawn evidence and the original final response.
Settle every attempt with record-close and actual close evidence or verified
terminal evidence/unsupported as dictated by capabilities. Never treat interruption
as host closure. An unreturned report is not DONE. Escalate at most once.

Strict reviewer registration adds --review-for-task-id and --review-kind; it is
read-only. Standard must run checks and record main review before verify.
