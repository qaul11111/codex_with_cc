# Dispatch assessment verification

Date: 2026-09-23. Branch: `codex/gpt6-adaptive-routing`.
Installed runtime: `codex-native-agents@personal`, version
`0.1.0+codex.20260923070822`.

## Resulting behavior

Before substantial development or investigation, main assesses the current
multi-agent instructions, user restrictions, an independent worker assignment,
useful concurrent main work and coordination overhead. It briefly explains a
split/model or a concrete reason for direct execution. Eligible work proceeds
through preflight and dispatch; scope or constraint changes require reassessment.

The core skill explicitly requests eligible delegation. This satisfies a host
instruction allowing an applicable skill to request delegation, but does not
override a hard prohibition or the user's no-agent/serial restriction. Main
reads the actual current instructions; the plugin does not toggle the task mode.

SessionStart and every UserPromptSubmit inject guidance without delegation-keyword
matching. Child provenance selects execution-only guidance. Existing spawn
envelope, model/effort and no-nested-dispatch checks remain in force. `advise`
accepts explicit mode/request/restriction inputs and returns concrete reasons;
unknown mode or absent useful main work does not recommend dispatch.

## Checks

- Source regression: **264 passed** in 11.59 seconds with Python 3.13,
  `PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 python3 -m pytest -q -p no:cacheprovider`.
- Plugin validation, both changed skill validators, Node syntax and diff
  whitespace checks passed.
- Installed/enabled state verified using the Codex CLI. Nine changed runtime and
  guidance files matched source byte-for-byte. The three plugin hooks were
  verified enabled and trusted using their exact current hashes.
- A fresh ephemeral app-server turn completed SessionStart and UserPromptSubmit
  hooks and reported the native skill, startup gate and per-prompt assessment
  context present.

An independent Sol medium model call interpreted seven **simulated** policy
scenarios using the installed core skill:

| Scenario | Observed choice |
| --- | --- |
| Explicit-request mode allowing applicable skills; useful independent work | Preflight and dispatch before substantial execution |
| Hard host prohibition even for skill requests | Main; explain prohibition |
| User explicitly forbids agents | Main; explain user restriction |
| One known 30-second typo, 2-minute coordination cost | Direct fix without workflow |
| No useful concurrent main work | Main; explain missing overlap |
| Earlier small task grows into independent modules | Reassess, then preflight and dispatch |
| Already spawned worker finds subtasks | No nested dispatch; report to main |

Local raw evidence is under `.codex/dispatch-assessment-20260923/evidence/`
(ignored), including `fresh-startup-probe-final.json` and `policy-exercise.json`.
The exercise used no scenario tools or workers, so it is not new proof of actual
automatic dispatch. Previous real worker results remain documented in
[GPT6-LIVE-SMOKE.md](GPT6-LIVE-SMOKE.md).

These are stronger instructions plus testable planning advice, not a background
scheduler or a guarantee that a model always complies. A new task is the supported
boundary for loading the update. The existing Android task was not messaged,
interrupted, restarted or reconfigured.
