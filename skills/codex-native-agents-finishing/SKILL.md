---
name: codex-native-agents-finishing
description: Finish native Codex agent workflows by checking reports, review gates, agent closure, repository verification, and final workflow acceptance.
---

# Native Agent Finishing

Use this after the critical work and reviews finish.

- Ensure every child is closed and every report is recorded.
- Run `native_agents.py verify --workflow-id <id>`.
- Run focused or full repository verification appropriate to accepted changes.
- Confirm each implementer has accepted spec, quality, and final-verifier gates, and parallel writable scopes did not overlap.
- Report only accepted work, rejected or blocked work, verification evidence, and residual risks. Do not claim completion without passing evidence.
