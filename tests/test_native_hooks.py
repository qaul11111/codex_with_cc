from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]


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
        },
    }


def denied(output: dict[str, object]) -> str:
    specific = output["hookSpecificOutput"]
    assert specific["permissionDecision"] == "deny"
    return str(specific["permissionDecisionReason"])


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


def test_model_override_is_allowed(run_hook, compliant_spawn) -> None:
    payload = compliant_spawn["tool_input"]
    assert isinstance(payload, dict)
    payload["model"] = "any-current-host-model"

    assert run_hook(compliant_spawn) == {}


def test_model_inheritance_is_allowed(run_hook, compliant_spawn) -> None:
    assert run_hook(compliant_spawn) == {}


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


@pytest.mark.parametrize(
    "command",
    [
        'rg -n "delegate_to_claude|claude" README.md',
        "cat hooks/subagent-gate-hook.mjs",
        "git show -- hooks/subagent-gate-hook.mjs",
    ],
)
def test_read_only_legacy_inspection_is_allowed(run_hook, command: str) -> None:
    output = run_hook(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "functions.shell_command",
            "tool_input": {"command": command},
        }
    )

    assert output == {}


@pytest.mark.parametrize(
    ("tool_name", "command", "expected"),
    [
        ("functions.exec_command", 'claude -p "work"', "direct claude execution"),
        ("Bash", "bash -c 'claude -p \"work\"'", "direct claude execution"),
        (
            "Bash",
            "zsh -lc 'delegate_to_claude.sh -TaskFile task.md'",
            "delegate_to_claude execution",
        ),
        ("Bash", 'command claude -p "work"', "direct claude execution"),
        ("Bash", 'env FOO=bar claude -p "work"', "direct claude execution"),
        ("Bash", "./scripts/delegate_to_claude.sh", "delegate_to_claude execution"),
        ("Bash", "bash -c 'claude -p \"work\" && echo done'", "direct claude execution"),
        (
            "Bash",
            "zsh -c 'echo ready; delegate_to_claude.sh -TaskFile task.md'",
            "delegate_to_claude execution",
        ),
        ("Bash", "bash -c 'echo ready || claude -p \"work\"'", "direct claude execution"),
        ("Bash", "zsh -c 'echo ready\nclaude -p \"work\"'", "direct claude execution"),
    ],
)
def test_executable_legacy_commands_are_denied(
    run_hook, tool_name: str, command: str, expected: str
) -> None:
    output = run_hook(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": tool_name,
            "tool_input": {"command": command},
        }
    )

    assert expected in denied(output)


@pytest.mark.parametrize(
    "command",
    [
        "bash -c 'printf \"claude -p work\"; echo done'",
        "zsh -c 'printf \"delegate_to_claude.sh\" && echo done'",
    ],
)
def test_safe_composite_shell_commands_are_allowed(run_hook, command: str) -> None:
    output = run_hook(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
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
