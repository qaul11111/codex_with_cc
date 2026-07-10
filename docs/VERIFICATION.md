# Verification

Run these checks from the repository root after changing the plugin:

```bash
jq empty .codex-plugin/plugin.json hooks/hooks.json skills/codex-native-agents/contract.json
node --check hooks/native-agent-gate-hook.mjs
PYTHONNOUSERSITE=1 python3 -m pytest -q
git diff --check
```

Validate each skill with the system validator:

```bash
python3 /Users/wxl/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/codex-native-agents
python3 /Users/wxl/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/codex-native-agents-planning
python3 /Users/wxl/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/codex-native-agents-dispatching
python3 /Users/wxl/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/codex-native-agents-worker
python3 /Users/wxl/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/codex-native-agents-reviewing
python3 /Users/wxl/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/codex-native-agents-finishing
```

Then validate the plugin package with `validate_plugin.py`. For an implementation workflow, `native_agents.py verify --workflow-id <id>` must show accepted spec review, quality review, and final verification evidence.
