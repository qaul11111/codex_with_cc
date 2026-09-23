from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
BLOCKED_AGENT_EXECUTABLE = "cla" + "ude"
BLOCKED_AGENT_WRAPPER = "delegate_to_" + BLOCKED_AGENT_EXECUTABLE


@pytest.fixture
def hook_script() -> Path:
    hooks_config = json.loads((REPO / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    command = hooks_config["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    match = re.search(r"'hooks', '([^']+\.mjs)'", command)
    assert match, command
    return REPO / "hooks" / match.group(1)


@pytest.fixture
def run_hook(hook_script: Path):
    def run(payload: dict[str, object]) -> dict[str, object]:
        result = subprocess.run(
            ["node", str(hook_script)],
            input=json.dumps(payload),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=REPO,
            encoding="utf-8",
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout) if result.stdout.strip() else {}

    return run


def task_envelope(**overrides: str) -> str:
    fields = {
        "WorkflowId": "native-auth",
        "TaskId": "implement-auth",
        "Role": "implementer",
        "TaskFile": ".codex/codex_native_agents/tasks/implement-auth.md",
        "Scope": "src/auth,tests/auth",
        "ModelProfile": "balanced",
        "Writable": "true",
        "Parallel": "false",
        "DispatcherRole": "main",
    }
    fields.update(overrides)
    body = "\n".join(f"{key}: {value}" for key, value in fields.items())
    return f"[NATIVE_CODEX_AGENT_TASK]\n{body}\n[/NATIVE_CODEX_AGENT_TASK]"


@pytest.fixture
def compliant_spawn() -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "spawn_agent",
        "tool_input": {
            "message": task_envelope(),
            "fork_context": False,
            "model": "gpt-6-sol",
            "reasoning_effort": "medium",
        },
    }


def denied(output: dict[str, object]) -> str:
    specific = output["hookSpecificOutput"]
    assert specific["permissionDecision"] == "deny"
    return str(specific["permissionDecisionReason"])


def write_transcript(
    path: Path,
    session_payload: dict[str, object],
    *subsequent_events: dict[str, object],
    trailing_newline: bool = True,
) -> Path:
    events = [{"type": "session_meta", "payload": session_payload}, *subsequent_events]
    path.write_text(
        "\n".join(json.dumps(event) for event in events) + ("\n" if trailing_newline else ""),
        encoding="utf-8",
    )
    return path


def test_hooks_config_has_only_hooks_and_native_entrypoint() -> None:
    config = json.loads((REPO / "hooks" / "hooks.json").read_text(encoding="utf-8"))

    assert set(config) == {"hooks"}
    assert set(config["hooks"]) == {"SessionStart", "UserPromptSubmit", "PreToolUse"}
    assert all(config["hooks"][event_name] for event_name in config["hooks"])
    for event_hooks in config["hooks"].values():
        for matcher in event_hooks:
            for hook in matcher["hooks"]:
                command = hook["command"]
                assert "native-agent-gate-hook.mjs" in command
                assert "subagent-gate-hook.mjs" not in command


def test_spawn_requires_native_task_envelope(run_hook) -> None:
    output = run_hook(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "multi_agent_v1__spawn_agent",
            "tool_input": {"message": "implement auth", "fork_context": False},
        }
    )

    assert "native task envelope" in denied(output)


def test_message_envelope_allows_compliant_spawn(run_hook, compliant_spawn) -> None:
    assert run_hook(compliant_spawn) == {}


def test_items_envelope_allows_compliant_spawn(run_hook, compliant_spawn) -> None:
    payload = compliant_spawn["tool_input"]
    assert isinstance(payload, dict)
    payload["message"] = "Read the assigned TaskFile and return the required report."
    payload["items"] = [{"type": "text", "text": task_envelope()}]

    assert run_hook(compliant_spawn) == {}


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("WorkflowId", "WorkflowId"),
        ("TaskId", "TaskId"),
        ("Role", "Role"),
        ("TaskFile", "TaskFile"),
        ("Scope", "Scope"),
        ("ModelProfile", "ModelProfile"),
        ("Writable", "Writable"),
        ("Parallel", "Parallel"),
        ("DispatcherRole", "DispatcherRole"),
    ],
)
def test_spawn_requires_each_task_envelope_field(run_hook, field: str, expected: str) -> None:
    lines = [
        line
        for line in task_envelope().splitlines()
        if not line.startswith(f"{field}:")
    ]
    output = run_hook(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "spawn_agent",
            "tool_input": {"message": "\n".join(lines), "fork_context": False},
        }
    )

    assert expected in denied(output)


def test_spawn_requires_main_dispatcher_role(run_hook, compliant_spawn) -> None:
    payload = compliant_spawn["tool_input"]
    assert isinstance(payload, dict)
    payload["message"] = task_envelope(DispatcherRole="worker")

    assert "DispatcherRole: main" in denied(run_hook(compliant_spawn))


@pytest.mark.parametrize("fork_context", [None, True, "true"])
def test_spawn_requires_explicit_false_fork_context(
    run_hook, compliant_spawn, fork_context: bool | str | None
) -> None:
    payload = compliant_spawn["tool_input"]
    assert isinstance(payload, dict)
    if fork_context is None:
        payload.pop("fork_context")
    else:
        payload["fork_context"] = fork_context

    assert "fork_context: false" in denied(run_hook(compliant_spawn))


def test_other_model_override_is_rejected(run_hook, compliant_spawn) -> None:
    payload = compliant_spawn["tool_input"]
    assert isinstance(payload, dict)
    payload["model"] = "any-current-host-model"

    assert "prepared profile" in denied(run_hook(compliant_spawn))


def test_implicit_model_inheritance_is_rejected(run_hook, compliant_spawn) -> None:
    compliant_spawn["tool_input"].pop("model")
    assert "prepared profile" in denied(run_hook(compliant_spawn))


@pytest.mark.parametrize(
    ("profile", "model", "effort"),
    [
        ("economy", "gpt-6-luna", "low"),
        ("balanced", "gpt-6-sol", "medium"),
        ("balancedHigh", "gpt-6-sol", "high"),
        ("frontier", "gpt-6-astra", "xhigh"),
    ],
)
def test_profile_dispatch_preserves_exact_model_and_effort(
    run_hook, compliant_spawn, profile, model, effort
) -> None:
    payload = compliant_spawn["tool_input"]
    payload.update(message=task_envelope(ModelProfile=profile), model=model,
                   reasoning_effort=effort)
    assert run_hook(compliant_spawn) == {}
    payload["reasoning_effort"] = "max"
    assert "prepared profile" in denied(run_hook(compliant_spawn))
    payload["reasoning_effort"] = effort
    payload["model"] = model.replace("gpt-6-", "gpt-5.6-")
    assert "prepared profile" in denied(run_hook(compliant_spawn))


def test_namespaced_spawn_agent_is_validated_by_tail(run_hook, compliant_spawn) -> None:
    compliant_spawn["tool_name"] = "functions.multi_agent_v1__spawn_agent"

    assert run_hook(compliant_spawn) == {}


def test_worker_nested_spawn_without_main_dispatch_envelope_is_denied(run_hook) -> None:
    output = run_hook(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "functions.spawn_agent",
            "tool_input": {
                "message": "As a worker, delegate this subtask to another spawn_agent.",
                "fork_context": False,
            },
        }
    )

    assert "native task envelope" in denied(output)


def test_main_session_meta_transcript_allows_compliant_spawn(
    run_hook, compliant_spawn, tmp_path: Path
) -> None:
    transcript = write_transcript(
        tmp_path / "main.jsonl",
        {"thread_source": "main", "source": {}},
        {
            "type": "event_msg",
            "payload": {
                "thread_source": "subagent",
                "parent_thread_id": "not-read-after-session-meta",
            },
        },
    )
    compliant_spawn["transcript_path"] = str(transcript)

    assert run_hook(compliant_spawn) == {}


@pytest.mark.parametrize("path_field", ["transcript_path", "transcriptPath"])
def test_subagent_session_meta_transcript_denies_spawn_despite_main_envelope(
    run_hook, compliant_spawn, tmp_path: Path, path_field: str
) -> None:
    transcript = write_transcript(
        tmp_path / "subagent.jsonl",
        {
            "source": {"subagent": {"thread_spawn": {"depth": 1}}},
            "thread_source": "subagent",
            "parent_thread_id": "parent-thread-id",
        },
    )
    compliant_spawn[path_field] = str(transcript)

    assert "child-session provenance" in denied(run_hook(compliant_spawn))


def test_large_main_session_meta_without_final_newline_allows_compliant_spawn(
    run_hook, compliant_spawn, tmp_path: Path
) -> None:
    transcript = write_transcript(
        tmp_path / "large-main.jsonl",
        {
            "thread_source": "main",
            "base_instructions": {"text": "main instructions " * 3_000},
        },
        trailing_newline=False,
    )
    compliant_spawn["transcript_path"] = str(transcript)

    assert run_hook(compliant_spawn) == {}


def test_large_subagent_session_meta_without_final_newline_denies_spawn(
    run_hook, compliant_spawn, tmp_path: Path
) -> None:
    transcript = write_transcript(
        tmp_path / "large-subagent.jsonl",
        {
            "source": {"subagent": {"thread_spawn": {"depth": 1}}},
            "thread_source": "subagent",
            "parent_thread_id": "parent-thread-id",
            "base_instructions": {"text": "subagent instructions " * 3_000},
        },
        trailing_newline=False,
    )
    compliant_spawn["transcript_path"] = str(transcript)

    assert "child-session provenance" in denied(run_hook(compliant_spawn))


@pytest.mark.parametrize(
    "provenance",
    [
        {"thread_source": "subagent"},
        {"parent_thread_id": "parent-thread-id"},
        {"parentThreadId": "parent-thread-id"},
        {"source": {"subagent": {"thread_spawn": {"depth": 1}}}},
    ],
)
def test_explicit_top_level_child_provenance_denies_spawn_despite_main_envelope(
    run_hook, compliant_spawn, provenance: dict[str, object]
) -> None:
    compliant_spawn.update(provenance)

    assert "child-session provenance" in denied(run_hook(compliant_spawn))


def test_missing_or_unreadable_transcript_does_not_deny_compliant_spawn(
    run_hook, compliant_spawn, tmp_path: Path
) -> None:
    compliant_spawn["transcript_path"] = str(tmp_path / "missing.jsonl")

    assert run_hook(compliant_spawn) == {}


@pytest.mark.parametrize(
    ("tool_name", "command"),
    [
        ("functions.exec_command", f'{BLOCKED_AGENT_EXECUTABLE} -p "work"'),
        ("Bash", f"bash -c '{BLOCKED_AGENT_EXECUTABLE} -p \"work\"'"),
        ("Bash", f"zsh -c {BLOCKED_AGENT_EXECUTABLE}"),
        ("Bash", f'command {BLOCKED_AGENT_EXECUTABLE} -p "work"'),
        ("Bash", f'env FOO=bar {BLOCKED_AGENT_EXECUTABLE} -p "work"'),
        ("Bash", f"./scripts/{BLOCKED_AGENT_WRAPPER}.sh"),
        ("Bash", f"zsh -c 'echo ready; {BLOCKED_AGENT_WRAPPER}.sh -TaskFile task.md'"),
        ("Bash", f"bash -c 'echo ready || {BLOCKED_AGENT_EXECUTABLE} -p \"work\"'"),
    ],
)
def test_legacy_agent_execution_is_denied_in_shell_boundaries(
    run_hook, tool_name: str, command: str
) -> None:
    output = run_hook(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": tool_name,
            "tool_input": {"command": command},
        }
    )

    assert "non-native agent executable" in denied(output)


def test_legacy_agent_execution_is_denied_when_exec_command_uses_cmd(run_hook) -> None:
    output = run_hook(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "functions.exec_command",
            "tool_input": {"cmd": f'{BLOCKED_AGENT_EXECUTABLE} -p "work"'},
        }
    )

    assert "non-native agent executable" in denied(output)


def test_legacy_agent_execution_is_denied_when_empty_command_and_malicious_cmd_coexist(
    run_hook,
) -> None:
    output = run_hook(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "functions.exec_command",
            "tool_input": {
                "command": "",
                "cmd": f'{BLOCKED_AGENT_EXECUTABLE} -p "work"',
            },
        }
    )

    assert "non-native agent executable" in denied(output)


@pytest.mark.parametrize(
    "command",
    [
        f'rg -n "{BLOCKED_AGENT_EXECUTABLE}" README.md',
        f"bash -c 'printf \"{BLOCKED_AGENT_EXECUTABLE} -p work\"; echo done'",
        "zsh -c 'printf safe && echo done'",
        "git show -- hooks/native-agent-gate-hook.mjs",
    ],
)
def test_read_only_and_print_shell_commands_are_allowed(run_hook, command: str) -> None:
    output = run_hook(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "functions.shell_command",
            "tool_input": {"command": command},
        }
    )

    assert output == {}


@pytest.mark.parametrize(
    "prompt",
    [
        "Explain README.",
        "Explain the delegation pattern in this README.",
        "解释文档里的子代理工作流",
    ],
)
def test_explanation_only_prompt_is_ignored(run_hook, prompt: str) -> None:
    assert run_hook({"hook_event_name": "UserPromptSubmit", "prompt": prompt}) == {}


def test_session_start_injects_compact_worker_guidance(run_hook) -> None:
    output = run_hook({"hook_event_name": "SessionStart", "source": "startup"})
    context = output["hookSpecificOutput"]["additionalContext"]

    assert "must not call spawn_agent" in context
    assert "CODEX_NATIVE_AGENTS.md" not in context
    assert len(context) < 900


@pytest.mark.parametrize(
    "prompt",
    [
        "Delegate this bounded task to a child agent.",
        "Start two subagents",
        "Use a child agent to review this change.",
        "请开启两个子代理",
        "Explain the plan, then delegate it to two workers",
    ],
)
def test_explicit_delegation_prompt_injects_compact_worker_guidance(run_hook, prompt: str) -> None:
    output = run_hook(
        {
            "hook_event_name": "UserPromptSubmit",
            "prompt": prompt,
        }
    )
    specific = output["hookSpecificOutput"]
    context = specific["additionalContext"]

    assert specific["hookEventName"] == "UserPromptSubmit"
    assert "fork_context: false" in context
    assert "must not call spawn_agent" in context
    assert "[NATIVE_CODEX_AGENT_TASK]" in context
    assert len(context) < 900
