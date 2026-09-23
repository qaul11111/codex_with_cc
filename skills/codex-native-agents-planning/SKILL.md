---
name: codex-native-agents-planning
description: Decide whether authorized development should stay in main or use native Astra workers, then define dependencies, access scopes, effort and acceptance risk.
---

# Native Agent Planning

Use the core skill's decision rules. Main may delegate within the authorized
assignment without asking again. Stay in main for short, uncertain or coupled
work. A split needs a concrete result and useful work that can proceed independently.

For a useful split, choose standard or strict before initialization. Map dependencies,
read/write access and main-owned integration files. Register producers first.
Choose role/complexity for effort; all routes use Astra. Estimate dispatch/review
cost and stop splitting when it exceeds expected saved time. The `advise` command
can record this reasoning without creating a workflow.

Read ../codex-native-agents/references/adaptive-workflows.md before dispatch.
Use ready/prepare-spawn to enforce slots, dependencies and access conflicts.
Strict implementers need exact-run spec/quality reviews and final verification;
standard uses current checks and main review. Do not plan redundant reviews for
ordinary changes. Preserve user scope and explicit serial/no-subagent restrictions.
