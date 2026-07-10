---
name: codex-native-agents-reviewing
description: Independently review native Codex worker output for task compliance, quality, evidence, scope, and required acceptance gates.
---

# Native Agent Reviewing

Read the task, worker report, changed files, and workflow record. The main thread decides acceptance.

- Spec review checks assignment compliance, scope, and acceptance criteria.
- Quality review checks correctness, maintainability, regression risk, and verification evidence.
- Reject reports with missing headings, invalid or mismatched status, unsupported role, unproven commands, or out-of-scope changes.
- After each returned review report, the main thread records it with `native_agents.py record-run --workflow-id <id> --task-id <review-id> --agent-id <agent-id> --report-file <report.md>`.
- An implementer is not acceptable until accepted spec review, quality review, and final verification all exist.
