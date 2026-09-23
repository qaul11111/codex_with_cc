---
name: codex-native-agents-dispatching
description: Dispatch eligible native GPT-6 task waves with exact model capabilities, prepared routing, independent scopes and original host evidence.
---

# Native Agent Dispatching

Read ../codex-native-agents/references/adaptive-workflows.md for command arguments.
Use the actual host tool catalog and preserve the emitted payload. Only main
spawns agents. Spawn the ready wave before waiting; process whichever finishes
first, then recompute readiness. Main continues only in non-conflicting scope.
The `ready` result lists eligible retries separately as `requiresEscalation`;
inspect the failure and use `prepare-spawn --escalate` for an appropriate retry.

Command sequence (all support the same --artifact-root where applicable):

```sh
python3 skills/codex-native-agents/scripts/native_agents.py init --workflow-id <id> --profile standard --host-capabilities <caps.json> --project-root <project>
python3 skills/codex-native-agents/scripts/native_agents.py validate-task --task-file <task.md> --role implementer
python3 skills/codex-native-agents/scripts/native_agents.py register-task --workflow-id <id> --task-id <task> --role implementer --task-file <task.md> --scope <path> --writable --parallel
python3 skills/codex-native-agents/scripts/native_agents.py ready --workflow-id <id>
python3 skills/codex-native-agents/scripts/native_agents.py prepare-spawn --workflow-id <id> --task-id <task>
python3 skills/codex-native-agents/scripts/native_agents.py record-spawn --workflow-id <id> --task-id <task> --agent-id <actual-id> --actual-model <prepared-model>
python3 skills/codex-native-agents/scripts/native_agents.py record-run --workflow-id <id> --task-id <task> --agent-id <actual-id> --report-file <report.md> --transcript-path <original-child.jsonl>
python3 skills/codex-native-agents/scripts/native_agents.py verify --workflow-id <id>
```

record-run requires matching spawn evidence and the original final response.
Omit --model-profile for automatic routing; set it only for an explicit fixed
profile. Preserve the prepared model and effort exactly, including when the
capability check selected a stronger model. Never substitute an old model ID.
Settle every attempt with record-close and actual close evidence or verified
terminal evidence/unsupported as dictated by capabilities. Never treat interruption
as host closure. An unreturned report is not DONE. Escalate at most once.

Strict reviewer registration adds --review-for-task-id and --review-kind; it is
read-only. Standard must run checks and record main review before verify.
