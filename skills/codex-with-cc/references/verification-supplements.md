# Historical verification supplements

Read this when an old, already superseded DONE delegate report abbreviated one
or more exact declared verification commands and the declared-tests gate now
fails on that historical report. The repair never edits history: it adds one
immutable, create-only sidecar per run that binds each missing command to
independently re-derivable evidence in the run's original raw Claude Code
stream. New reports can never satisfy an old report's gate, and a supplement
is never a substitute for a valid current final report.

## Recording (main thread only)

```bash
python3 "<installed-workflow-root>/scripts/runtime.py" record-verification-supplement \
  -RunId <superseded-run-id> -ArtifactRoot <artifact-root>
```

The command is explicit and main-thread driven. It writes
`verification-supplement_<run-id>.json` with create-only semantics: it never
overwrites, and a repeated call re-derives the evidence and verifies the
existing sidecar byte content instead of rewriting it. A diverging existing
sidecar fails safe. There are no user-supplied success claims and no arbitrary
replacement reports; every command in the sidecar must come from the stream.

## Eligibility (strict, fail-closed)

All of the following must hold, verified from the original artifacts at record
time and again at every acceptance:

- The run is superseded: it is not the task's current `latestRunId`.
- Existing artifact validation (`verify-artifacts`) passes unmodified.
- The run is a completed, non-dry-run, non-fallback, non-report-recovered,
  single-attempt (`retryCount` 0) `claude_code` run.
- The report Status and Final Result are both DONE.
- Config, status, report, and `rawStreamPath` agree on the exact
  run/task/workflow/session identity.
- The report's Verification section omits at least one exact declared test
  string (or its `<run-id>`-substituted variant); a supplement is recorded
  only for those missing commands.

Current reports and non-DONE reports cannot use this route to avoid normal
reporting; the command refuses them.

## Evidence rules

For each missing declared command the raw stream parser requires, in the same
single session as the run's only attempt:

- Exactly one assistant `tool_use` block named `Bash` whose `input.command`
  equals the declared command exactly (no substring, prefix, or whitespace
  matching), matched by unique tool_use id to
- exactly one later user `tool_result` block with `is_error` explicitly false
  and a structured `tool_use_result` object whose `interrupted` is explicitly
  false, containing only allowlisted fields (`stdout`, `stderr`,
  `interrupted`, `isImage`, `noOutputExpected`, `exitCode`), with no timeout,
  background, pending, or task handle, and a zero `exitCode` when one is
  supplied.

Missing, duplicate, ambiguous, mismatched, reordered, or failed results are
rejected, as are multi-attempt runs, wrong sessions, malformed stream records,
symlinked or root-escaping stream paths, and unsafe run ids. Success is never
inferred from stdout wording, and text/Read/StructuredOutput records are never
proof. Known leading `[claude-code:...]` CLI warning lines before the first
conversation record are tolerated; malformed JSON records are not.

Evidence boundary: a bare Claude tool result without `exitCode` proves only
tool-reported success. The sidecar records `evidence: "tool-reported-success"`
and `exitCode: null` for that case; it does not invent a numeric exit 0. Only a
tool result that actually carries `exitCode: 0` is recorded as
`"exit-code-0"`.

## Sidecar contents and acceptance

The sidecar records the schema id and version, workflow/task/run/session
identity, the exact missing commands, the original use/result record line
positions and uuids, and SHA256 of the original config, status, report, and
raw stream. Every acceptance (`verify-workflow`, `verify-final-inputs`)
rehashes those originals, re-derives the evidence from the stream, and
compares the sidecar strictly; stored booleans are never trusted. With no
sidecar the historical gate fails unchanged and the diagnostic names the
offending RunId and TaskId. A bad sidecar fails verification instead of being
silently ignored. Full workflow gates, review gates, final-verifier current
bindings, and lifecycle termination checks are unchanged.

## Security posture

A sidecar is a local audit record. It is not tamper-proof against a hostile
same-user process that can rewrite both the originals and the sidecar, and it
does not replace a valid current final report. Its purpose is to preserve
history while making the historical evidence independently checkable, so that
acceptance never depends on trusting an abbreviated report or an editable
aggregate.

## Hardening notes (evidence-repair rework)

- Symlinks are rejected BEFORE any resolve in every path component. Every
  component of a supplied artifact root is walked with lstat (the
  fixed_launcher.py component-walk pattern) before any canonicalization, so an
  ancestor alias such as `base/alias/artifacts` with `alias -> base/actual`
  is rejected even though the final component is a real directory; relative
  paths are made absolute against the current directory first, dangling
  symlinks are still detected, and missing components fail closed. An
  untrusted alias is never silently canonicalized — callers must pass the
  canonical root explicitly. The run's config/status/report, the raw stream,
  and the sidecar itself carry the same final-component and in-root ancestor
  checks. The sidecar path is never pre-resolved, so an in-root sidecar
  symlink (even dangling) fails instead of being collapsed to its target, and
  no sidecar is ever created through a dangling symlink.
- The recorded raw stream must be the run's exact expected stream file
  (`stream_<run-id>.jsonl` in the artifact root) and must match the workflow
  run entry; any in-root lookalike with identical bytes is rejected.
- The declared-tests gate validates EVERY existing sidecar belonging to a
  verified run before any skip branch. A forged or now-inapplicable sidecar
  (current run, non-DONE report, fully reported run, dry-run) is an error,
  never silently ignored. Artifact and supplement verification never recurse
  into each other.
- A user record carrying multiple tool_result blocks cannot attribute its
  record-level tool_use_result to any one block; such ambiguous candidate
  records are rejected (unrelated multi-result records are ignored). Stream
  metadata (session_id, uuid) must be strings; reads stay bounded.

## Serial same-task retries and the parallel scope gate

Serial historical retries of the SAME implementer TaskId share scope by
definition. `enforce_parallel_implementer_scope` grants a narrow exception for
overlapping scopes within one TaskId ONLY when each run in the pair has
exactly one task/run/native-thread agent attempt with pinned terminal evidence
under the terminal-evidence policy, that evidence is re-verified
(`lifecycle.execution_evidence` recomputed from the originals and compared
against the stored value, binding transcript and config/status/report hashes,
non-dry/non-fallback/non-recovered terminal runner, exited PID), and the
re-verified timing proves strict serial execution.

The candidate execution interval is the authenticated host terminal turn
startedAt to the ORIGINAL PINNED runner status updatedAt (hash-bound by the
re-verified evidence), with start <= end <= host terminalAt. The earlier
runner's pinned completion must be strictly before the later host turn starts.
Host terminalAt alone is never the end bound: a carrier's final relay can
outlast the next child spawn without any worker write overlap. Editable
aggregate timestamps, RunId ordering, and the current clock are never used.
Missing, malformed, duplicated, changed, uncertain, or reversed timing remains
fail-closed with TaskId and RunId diagnostics. Only the evidence of the
overlapping pair is validated; unrelated in-flight attempts are not required
to be settled, and the whole lifecycle gate is unchanged. Distinct-task
overlaps, missing scopes, and dry runs stay rejected as before.
