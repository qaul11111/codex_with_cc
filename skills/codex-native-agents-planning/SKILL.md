---
name: codex-native-agents-planning
description: Choose direct work or native GPT-6 workers for authorized development, then define dependencies, access scopes, model effort and acceptance risk.
---

# Native Agent Planning

Read the assessment rules in [the core skill](../codex-native-agents/SKILL.md).
Before substantial execution, state the actual multi-agent mode and a concrete
split or reason to work directly. The core skill explicitly requests eligible
delegation under a mode that allows skill-requested workers; a hard prohibition
or user no-agent/serial restriction still wins. Do not infer mode from the main
model or change it automatically. A split needs a concrete result and useful
work that main can do independently. Dispatch when eligible; reassess if scope
or constraints change. Small direct tasks need no workflow.

For a useful split, choose standard or strict before initialization. Map dependencies,
read/write access and main-owned integration files. Register producers first.
Choose role/complexity for the Luna/Sol/Astra route and inspect actual host support.
Use an explicit profile only to honor a deliberate model choice. Estimate dispatch/review
cost and stop splitting when it exceeds expected saved time. The `advise` command
can record this reasoning without creating a workflow.

Read ../codex-native-agents/references/adaptive-workflows.md before dispatch.
Use ready/prepare-spawn to enforce slots, dependencies and access conflicts.
Strict implementers need exact-run spec/quality reviews and final verification;
standard uses current checks and main review. Do not plan redundant reviews for
ordinary changes. Preserve user scope and explicit serial/no-subagent restrictions.
