---
name: codex-native-agents-reviewing
description: Independently review native Codex worker output for task compliance, quality, evidence, scope, and required acceptance gates.
---

# Native Agent Reviewing

Read the task, worker report, changed files, and workflow record. The main thread decides acceptance.

- Spec review checks assignment compliance, scope, and acceptance criteria.
- Quality review checks correctness, maintainability, regression risk, and verification evidence.
- Reject reports with missing headings, invalid or mismatched status, unsupported role, unproven commands, or out-of-scope changes.
- Record accepted or rejected review results through `native_agents.py`.
- An implementer is not acceptable until accepted spec review, quality review, and final verification all exist.
