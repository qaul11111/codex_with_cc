# Local Development Installation

This repository is the local development source for `codex-native-agents` from [qaul11111/codex_with_cc](https://github.com/qaul11111/codex_with_cc). It is not a published marketplace plugin.

## User-Scoped Setup

Run these commands from a disposable directory, then replace only the newly
generated scaffold after inspecting it. This creates a personal local source;
it does not publish anything.

```bash
python3 /Users/wxl/.codex/skills/.system/plugin-creator/scripts/create_basic_plugin.py codex-native-agents --with-marketplace
find ~/plugins/codex-native-agents -maxdepth 2 -type f -print
# Continue only after confirming this is the new scaffold and contains no user work.
rm -rf ~/plugins/codex-native-agents
ln -s "$(pwd)" ~/plugins/codex-native-agents
python3 /Users/wxl/.codex/skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py ~/plugins/codex-native-agents
python3 /Users/wxl/.codex/skills/.system/plugin-creator/scripts/read_marketplace_name.py
codex plugin add codex-native-agents@personal
```

Do not hand-edit `marketplace.json` or `~/.codex/config.toml`. Confirm that the
old delegation plugin remains disabled before enabling this one, then reload
Codex if the skill list has not refreshed.

Do not copy individual skills into a target project. Keep the repository as the single local source so hooks, the contract, skills, and verifier remain aligned.

## Post-Install Check

Run from the repository root:

```bash
jq empty .codex-plugin/plugin.json hooks/hooks.json skills/codex-native-agents/contract.json
node --check hooks/native-agent-gate-hook.mjs
PYTHONNOUSERSITE=1 python3 -m pytest -q
```

For a real workflow, create a TaskFile under `.codex/codex_native_agents/tasks/`, validate and register it with `skills/codex-native-agents/scripts/native_agents.py`, then dispatch through the native skills. Child prompts must include the full task envelope and `fork_context: false`.
