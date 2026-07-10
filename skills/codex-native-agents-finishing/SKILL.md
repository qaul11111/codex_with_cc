---
name: codex-native-agents-finishing
description: Finish native Codex agent workflows by checking reports, review gates, agent closure, repository verification, and final workflow acceptance.
---

# Native Agent Finishing

Use this after the critical work and reviews finish.

- Ensure every child is closed and every returned report has been recorded with `python3 skills/codex-native-agents/scripts/native_agents.py record-run --workflow-id <id> --task-id <task-id> --agent-id <agent-id> --report-file <report.md>`, followed by `python3 skills/codex-native-agents/scripts/native_agents.py record-close --workflow-id <id> --task-id <task-id> --agent-id <agent-id> --status closed`. Every run requires matching spawn evidence, and each close must bind its exact spawn attempt and agent ID.
- An interrupted or replaced child with no worker report still requires `close_agent` and `record-close` before a replacement attempt is recorded. Run `python3 skills/codex-native-agents/scripts/native_agents.py verify --workflow-id <id>` and inspect its workflow JSON for requested profile, actual model or `inherit_parent`, fallback reason, report, review, and closure snapshot evidence. Every registered task must have a DONE latest run and every spawn attempt must have matching closure evidence before acceptance.
- Run focused or full repository verification appropriate to accepted changes.
- Confirm each implementer has accepted spec, quality, and final-verifier gates, and parallel writable scopes did not overlap.
- Report only accepted work, rejected or blocked work, verification evidence, and residual risks. Do not claim completion without passing evidence.
