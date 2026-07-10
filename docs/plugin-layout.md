# Plugin Layout

```text
.codex-plugin/plugin.json
hooks/hooks.json
hooks/native-agent-gate-hook.mjs
skills/codex-native-agents/                 # contract and local verifier
skills/codex-native-agents-{planning,dispatching,worker,reviewing,finishing}/
```

The local development source is [qaul11111/codex_with_cc](https://github.com/qaul11111/codex_with_cc). It is installed at user scope through Codex's local plugin flow, not from a marketplace.

The core contract owns roles, model profiles, task sections, report headings, and workflow gates. The five focused skills refer to that contract instead of duplicating it. Hooks only validate native dispatch protocol fields and do not launch agents.
