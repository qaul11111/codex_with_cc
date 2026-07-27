# Fixed Launcher

Codex-with-cc 1.2.0 introduces a stable, no-argument launcher for macOS so the Codex App can approve one fixed command while per-task metadata stays isolated in a `launch.json` descriptor directory.

## Why

- The App exec-policy is simpler when the approved command never changes.
- Task metadata (TaskFile, WorkflowId, TaskId, Role, SessionKey, scopes, tests, review metadata, session mode, timeouts, retries) lives in structured JSON instead of a long shell command.
- Concurrent child threads are isolated: one descriptor directory per attempt, with no shared mutable pointer.

## Install

```bash
"<installed-workflow-root>/macos_scripts/install-codex-with-cc-launch.sh"
```

This writes `${CODEX_HOME:-$HOME/.codex}/bin/codex-with-cc-launch`. The installer checks that `CODEX_HOME` and `CODEX_HOME/bin` are owned by the current user and not group/other writable. The write is atomic (temp file + rename). Rerunning the installer atomically repoints the stable launcher to the current installed workflow root.

## Descriptor

Place a `launch.json` in a dedicated directory per child attempt:

```json
{
  "version": "1.2.0",
  "invocation": "codex_with_cc_workflow",
  "childThread": {
    "threadId": "<CODEX_THREAD_ID>"
  },
  "projectWorkingDirectory": "<absolute project root>",
  "taskFile": "./.codex/codex_with_cc/tasks/<yyyyMMdd>/<HHmmssfff>-<short-id>-<task>.md",
  "workflowId": "<workflow-id>",
  "taskId": "<task-id>",
  "role": "implementer",
  "sessionKey": "<stable-session-key>",
  "scope": ["<changed-or-inspected-path>"],
  "tests": ["pytest -q"],
  "session": {
    "sessionMode": "PrimaryReuse",
    "allowParallel": false
  },
  "bypassPermissions": true
}
```

Reviewer tasks add a `review` block:

```json
"review": {
  "reviewForTaskId": "<implementer-task-id>",
  "reviewForRunId": "<implementer-run-id>",
  "reviewKind": "spec"
}
```

All delegate CLI arguments are supported through the descriptor: scopes, tests, dependencies, session mode/parallel controls, artifact/output paths, timeouts, retries, heartbeat, locks, model, name, budget, permission flags, trusted local fallback (`trustedLocalFallback`), and dry-run.

## Invoke

The terminal tool sets the descriptor directory as its working directory and executes the exact literal no-argument launcher command:

```bash
/Users/<user>/.codex/bin/codex-with-cc-launch
```

Codex App normally records this as `["/bin/zsh", "-c", "/Users/<user>/.codex/bin/codex-with-cc-launch"]`. Do not add another `zsh -c` wrapper to the terminal tool command.

The launcher accepts no arguments. It sets `CODEX_CLAUDE_CHILD_THREAD=1`, validates the descriptor schema (all fields, sub-fields, types, integer ranges), checks descriptor directory and `launch.json` ownership/mode, checks thread binding, verifies `projectWorkingDirectory` (absolute, existing, owned, no symlinks, writable), verifies `taskFile` (relative, no `..`, resolves inside project root, readable, no symlinks), claims the descriptor atomically with owner-only mode, and runs the existing delegate runtime.

## Codex App exec-policy example

Use this `.rules` format. Do not add it to the user's live config automatically.

```starlark
prefix_rule(pattern=["/bin/zsh", "-c", "/Users/<user>/.codex/bin/codex-with-cc-launch"], decision="allow")
```

The copy-ready source is `examples/exec-policy.example.rules`. Never allow a generic `["/bin/zsh", "-c"]` prefix or a one-element launcher prefix, because both are broader than the App-recorded command.

## Concurrency

- One descriptor directory per child attempt.
- No global current-pointer file.
- Atomic `claimed` file with owner-only mode prevents double execution.
- Failed runs remain claimed; retry uses a new descriptor directory.

## Security

- No command-line arguments.
- Installer checks ownership and mode of `CODEX_HOME` and `CODEX_HOME/bin`; writes atomically; embeds `sys.executable`.
- `launch.json` opened without following symlinks (O_NOFOLLOW); verified as regular file owned by current user, not group/other writable.
- Descriptor directory verified as owned by current user, not group/other writable, no symlinks.
- `projectWorkingDirectory` must be absolute, existing, owned, not group/other writable, symlink-free.
- `taskFile` must be relative, no `..`, resolves inside project root; absolute/escaping/symlinked paths rejected.
- Non-fallback descriptors require `CODEX_THREAD_ID` to match `childThread.threadId`. `trustedLocalFallback: true` maps to the existing `-TrustedLocalFallback` runtime flag.

## Upgrade and rollback

- Upgrade: rerun the installer from the new plugin version. The launcher is atomically repointed.
- Rollback: replace the launcher with the previous version's launcher, or delete it and reinstall from the desired version.
