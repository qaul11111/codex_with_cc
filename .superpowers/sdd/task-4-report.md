# Task 4 Report: Native Spawn Hook Gate

## Status

DONE

## Summary

Replaced the legacy Claude-specific hook entry with a standalone Node native
agent gate. The gate reads the native contract, validates complete main-thread
task envelopes from `message` and text `items`, requires literal boolean
`fork_context: false`, permits both explicit and inherited models, and blocks
only executable legacy Claude paths. Session and trigger context is compact and
states that workers must not recursively call `spawn_agent`.

## Changed Files

- `hooks/hooks.json`
- `hooks/native-agent-gate-hook.mjs`
- `tests/test_native_hooks.py`
- `.superpowers/sdd/task-4-report.md`

## RED/GREEN Tests

RED:

```text
PYTHONNOUSERSITE=1 python3 -m pytest tests/test_native_hooks.py -q
Result: 18 failed, 11 passed in 0.92s.
```

The current `subagent-gate-hook.mjs` denied native envelopes for legacy
Claude-specific metadata such as `reasoning_effort`, child-thread markers, and
delegate arguments; it also failed the native hook schema and compact-context
requirements.

GREEN:

```text
PYTHONNOUSERSITE=1 python3 -m pytest tests/test_native_hooks.py -q
Result: 29 passed in 0.84s.

node --check hooks/native-agent-gate-hook.mjs
Result: passed.

jq empty hooks/hooks.json
Result: passed.
```

## Commits

- `feat: gate native Codex agent dispatch`

## Self-review

- `hooks/hooks.json` has only the top-level `hooks` key and all three events
  invoke `native-agent-gate-hook.mjs`.
- The hook is a standalone Node process and imports only Node standard-library
  modules; it does not import or execute Python.
- Native spawn detection uses the tool-name tail, including `__`, dot, slash,
  and colon namespaces.
- Envelope validation consumes plain `message` plus every `items` entry whose
  type is `text`, checks all contract-required fields, and requires
  `DispatcherRole: main`.
- `fork_context` passes only as the literal boolean `false`; model is never
  compared to a fixed slug.
- Shell validation allows `rg`, `cat`, and `git show` inspection that mentions
  legacy paths while denying executable `claude` and `delegate_to_claude` paths.

## Concerns

- The focused pytest command emits the existing `pytest_asyncio` deprecation
  warning for an unset default loop scope; the test result is unaffected.
- Legacy hook tests still target `subagent-gate-hook.mjs` and were not migrated
  because Task 4 scope is limited to the new native gate files.
