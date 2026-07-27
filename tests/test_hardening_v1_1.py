from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from tests.task_helpers import compliant_task


REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "skills" / "codex-with-cc" / "scripts"
HOOK_SCRIPT = REPO / "hooks" / "subagent-gate-hook.mjs"
DELEGATE = SCRIPTS / "delegate_to_claude.py"
VERIFY_WORKFLOW = SCRIPTS / "verify_delegate_workflow.py"
sys.path.insert(0, str(SCRIPTS))

import codex_with_cc_runtime.workflow as workflow_runtime
import codex_with_cc_runtime.sessions as sessions_runtime
from codex_with_cc_runtime.claude_cli import new_claude_cli_args, update_stream_capture
from codex_with_cc_runtime.io_utils import load_json, write_json


REPORT = """Status
DONE

Role
researcher

Summary
Completed the audit probe.

Changed Files
None

Verification
- hardening probe passed

Findings
None

Final Result
DONE

Risks Or Follow-ups
None
"""


def run_hook(payload: dict) -> dict:
    result = subprocess.run(
        ["node", str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=REPO,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout) if result.stdout.strip() else {}


def run_python(script: Path, *args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=REPO,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "CODEX_CLAUDE_CHILD_THREAD": "1",
            "CODEX_THREAD_ID": "",
            "PYTHONDONTWRITEBYTECODE": "1",
            **(env_extra or {}),
        },
        timeout=15,
    )


def test_exec_command_cmd_field_is_covered_by_hook_gate() -> None:
    output = run_hook(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "functions.exec_command",
            "tool_input": {"cmd": 'claude -p "do delegated work"'},
        }
    )

    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "direct Claude CLI" in output["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize(
    "command",
    [
        'env claude -p "work"',
        'env -u FOO claude -p "work"',
        '/usr/bin/env claude -p "work"',
        'sudo -u root claude -p "work"',
        'command claude -p "work"',
        'exec claude -p "work"',
        'ANTHROPIC_LOG=1 claude -p "work"',
        'bash -c "env -u FOO claude -p work"',
    ],
)
def test_shell_prefixes_cannot_bypass_direct_claude_gate(command: str) -> None:
    output = run_hook(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "functions.exec_command",
            "tool_input": {"cmd": command},
        }
    )

    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize(
    "command",
    [
        "env echo claude",
        "command -v claude",
        "printf 'claude -p work'",
        "bash --norc script.sh",
    ],
)
def test_shell_inspection_and_arguments_do_not_trigger_direct_claude_gate(command: str) -> None:
    assert run_hook(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "functions.exec_command",
            "tool_input": {"cmd": command},
        }
    ) == {}


def test_session_context_is_compact_and_not_reinjected_in_full() -> None:
    output = run_hook({"hook_event_name": "SessionStart", "source": "startup"})
    context = output["hookSpecificOutput"]["additionalContext"]

    assert len(context) < 5000
    assert "Below is the full content" not in context
    assert "record every spawned agent id" in context
    assert "close every agent attempt" in context


def test_parallel_workflow_updates_do_not_lose_tasks(monkeypatch) -> None:
    with tempfile.TemporaryDirectory(prefix="codex_with_cc_workflow_lock_") as tmp:
        root = Path(tmp)
        path = workflow_runtime.workflow_path(root, "wf-race")
        write_json(path, workflow_runtime.empty_workflow("wf-race"))
        original_load = workflow_runtime.load_json

        def synchronized_load(candidate: Path) -> dict:
            data = original_load(candidate)
            if candidate == path:
                time.sleep(0.05)
            return data

        monkeypatch.setattr(workflow_runtime, "load_json", synchronized_load)

        def update(task_id: str) -> None:
            output = root / f"{task_id}.md"
            output.write_text(REPORT, encoding="utf-8")
            workflow_runtime.update_workflow_record(
                root,
                "wf-race",
                task_id,
                "researcher",
                [],
                [],
                [],
                task_id,
                root / f"{task_id}-config.json",
                root / f"{task_id}-status.json",
                output,
                root / f"{task_id}-prompt.md",
                root / f"{task_id}-stream.jsonl",
                root / f"{task_id}-trace.log",
                "completed",
            )

        threads = [threading.Thread(target=update, args=(task_id,)) for task_id in ("task-a", "task-b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert sorted(load_json(path)["tasks"]) == ["task-a", "task-b"]


def test_accepted_reviews_must_bind_to_latest_implementer_run() -> None:
    task = {
        "taskId": "implement",
        "role": "implementer",
        "status": "completed",
        "latestRunId": "run-2",
        "lastReportStatus": "DONE",
        "lastReportFinalResult": "DONE",
        "reviews": {
            "spec": {"reviewDecision": "accepted", "reviewedRunId": "run-1"},
            "quality": {"reviewDecision": "accepted", "reviewedRunId": "run-1"},
        },
    }

    assert workflow_runtime.implementer_review_decision(task) == "pending-review"


def test_final_acceptance_requires_current_final_verifier() -> None:
    implementer = {
        "taskId": "implement",
        "role": "implementer",
        "status": "completed",
        "latestRunId": "run-1",
        "lastReportStatus": "DONE",
        "lastReportFinalResult": "DONE",
        "reviewDecision": "accepted",
        "reviews": {
            "spec": {"reviewDecision": "accepted", "reviewedRunId": "run-1", "runId": "spec-1"},
            "quality": {"reviewDecision": "accepted", "reviewedRunId": "run-1", "runId": "quality-1"},
        },
    }
    workflow = {"tasks": {"implement": implementer}}

    workflow_runtime.update_workflow_acceptance(workflow)

    assert workflow["finalAcceptance"]["status"] == "pending-final-verifier"


def test_final_verifier_snapshot_does_not_float_to_newer_runs() -> None:
    workflow = {
        "tasks": {
            "implement": {
                "taskId": "implement",
                "role": "implementer",
                "latestRunId": "run-1",
                "reviews": {
                    "spec": {"runId": "spec-1"},
                    "quality": {"runId": "quality-1"},
                },
            }
        }
    }
    captured = workflow_runtime.final_verifier_snapshot(workflow)
    workflow["tasks"]["implement"]["latestRunId"] = "run-2"
    workflow["tasks"]["implement"]["reviews"] = {
        "spec": {"runId": "spec-2"},
        "quality": {"runId": "quality-2"},
    }
    workflow["tasks"]["final"] = {
        "taskId": "final",
        "role": "final-verifier",
        "latestRunId": "final-1",
        "status": "completed",
        "lastReportStatus": "DONE",
        "lastReportFinalResult": "DONE",
        "reviewDecision": "accepted",
        "verifiedImplementerRuns": captured,
        "updatedAt": "2026-07-27T00:00:00Z",
    }

    assert workflow_runtime.current_final_verifier(workflow) is None


def test_failed_research_workflow_is_not_accepted() -> None:
    workflow = {
        "tasks": {
            "research": {
                "taskId": "research",
                "role": "researcher",
                "status": "failed",
                "lastReportStatus": "FAIL",
                "lastReportFinalResult": "FAIL",
                "reviewDecision": "failed",
            }
        }
    }

    workflow_runtime.update_workflow_acceptance(workflow)

    assert workflow["finalAcceptance"]["status"] == "failed"


def test_dry_run_workflow_cannot_be_accepted() -> None:
    with tempfile.TemporaryDirectory(prefix="codex_with_cc_dry_run_gate_") as tmp:
        root = Path(tmp)
        artifact_root = root / "artifacts"

        for task_id, role, extra in (
            ("implement", "implementer", ()),
            ("spec", "reviewer", ("-ReviewForTaskId", "implement", "-ReviewForRunId", "dry-run", "-ReviewKind", "spec")),
            ("quality", "reviewer", ("-ReviewForTaskId", "implement", "-ReviewForRunId", "dry-run", "-ReviewKind", "quality")),
            ("final", "final-verifier", ()),
        ):
            task_file = root / f"{task_id}.md"
            task_file.write_text(compliant_task(f"{task_id} dry-run task"), encoding="utf-8")
            result = run_python(
                DELEGATE,
                "-TaskFile",
                str(task_file),
                "-WorkflowId",
                "wf-dry-run",
                "-TaskId",
                task_id,
                "-Role",
                role,
                "-SessionKey",
                "wf-dry-run",
                "-ArtifactRoot",
                str(artifact_root),
                *extra,
                "-TrustedLocalFallback",
                "-DryRun",
            )
            assert result.returncode == 0, result.stdout + result.stderr

        verified = run_python(
            VERIFY_WORKFLOW,
            "-WorkflowId",
            "wf-dry-run",
            "-ArtifactRoot",
            str(artifact_root),
        )

        assert verified.returncode != 0
        workflow = load_json(workflow_runtime.workflow_path(artifact_root, "wf-dry-run"))
        assert workflow["finalAcceptance"]["status"] == "dry-run"


def test_delegate_requires_codex_thread_id_without_explicit_local_fallback() -> None:
    with tempfile.TemporaryDirectory(prefix="codex_with_cc_thread_id_gate_") as tmp:
        root = Path(tmp)
        task_file = root / "task.md"
        task_file.write_text(compliant_task("verify thread identity gate"), encoding="utf-8")
        result = run_python(
            DELEGATE,
            "-TaskFile",
            str(task_file),
            "-WorkflowId",
            "wf-thread-id",
            "-TaskId",
            "research",
            "-Role",
            "researcher",
            "-SessionKey",
            "wf-thread-id",
            "-ArtifactRoot",
            str(root / "artifacts"),
            "-DryRun",
        )

        assert result.returncode != 0
        assert "CODEX_THREAD_ID is required" in result.stderr


def test_review_roles_default_to_independent_sessions() -> None:
    assert sessions_runtime.default_session_mode("implementer") == "PrimaryReuse"
    assert sessions_runtime.default_session_mode("reviewer") == "ParallelPool"
    assert sessions_runtime.default_session_mode("final-verifier") == "ParallelPool"


def test_heartbeat_lease_renewal_never_waits_for_session_lock(monkeypatch) -> None:
    observed: dict[str, int] = {}

    def locked_update(state_path, lock_path, key, timeout_seconds, update):
        observed["timeout"] = timeout_seconds
        raise sessions_runtime.DelegateError("lock busy")

    monkeypatch.setattr(sessions_runtime, "update_session_state", locked_update)
    lease = sessions_runtime.SessionLease("PrimaryReuse", "session-1", True, None)

    assert sessions_runtime.renew_session_lease(
        Path("/tmp/state.json"),
        Path("/tmp/state.lock"),
        "session-key",
        lease,
        "run-1",
    ) is False
    assert observed["timeout"] == 0


def test_silent_claude_process_is_terminated_and_recorded() -> None:
    with tempfile.TemporaryDirectory(prefix="codex_with_cc_silent_timeout_") as tmp:
        root = Path(tmp)
        bin_dir = root / "bin"
        artifact_root = root / "artifacts"
        bin_dir.mkdir()
        fake_claude = bin_dir / "claude"
        fake_claude.write_text("#!/bin/sh\ncat >/dev/null\nsleep 30\n", encoding="utf-8")
        fake_claude.chmod(0o755)
        task_file = root / "task.md"
        task_file.write_text(compliant_task("exercise silent timeout"), encoding="utf-8")

        started = time.monotonic()
        result = run_python(
            DELEGATE,
            "-TaskFile",
            str(task_file),
            "-WorkflowId",
            "wf-timeout",
            "-TaskId",
            "research",
            "-Role",
            "researcher",
            "-SessionKey",
            "wf-timeout",
            "-ArtifactRoot",
            str(artifact_root),
            "-SilentTimeoutSeconds",
            "1",
            "-ExecutionTimeoutSeconds",
            "10",
            "-HeartbeatSeconds",
            "1",
            "-MaxRetryCount",
            "0",
            "-TrustedLocalFallback",
            env_extra={"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"},
        )

        assert result.returncode != 0
        assert time.monotonic() - started < 8
        status = load_json(next(artifact_root.glob("status_*.json")))
        assert status["timeoutKind"] == "silent"
        assert status["failureDisposition"] == "NEED_HUMAN_INTERVENTION"
        assert status["attempts"][0]["timeoutKind"] == "silent"


def test_agent_attempt_must_be_closed_before_acceptance() -> None:
    with tempfile.TemporaryDirectory(prefix="codex_with_cc_agent_close_") as tmp:
        root = Path(tmp)
        output = root / "report.md"
        output.write_text(REPORT, encoding="utf-8")
        workflow_runtime.record_agent_spawn(root, "wf-close", "research", "agent-1")
        workflow_runtime.update_workflow_record(
            root,
            "wf-close",
            "research",
            "researcher",
            [],
            [],
            [],
            "run-1",
            root / "config.json",
            root / "status.json",
            output,
            root / "prompt.md",
            root / "stream.jsonl",
            root / "trace.log",
            "completed",
            codex_thread_id="agent-1",
        )

        path = workflow_runtime.workflow_path(root, "wf-close")
        assert load_json(path)["finalAcceptance"]["status"] == "pending-agent-close"

        workflow_runtime.record_agent_close(root, "wf-close", "research", "agent-1")

        assert load_json(path)["finalAcceptance"]["status"] == "accepted"


def test_child_run_without_explicit_spawn_record_fails_closed() -> None:
    with tempfile.TemporaryDirectory(prefix="codex_with_cc_agent_spawn_") as tmp:
        root = Path(tmp)
        output = root / "report.md"
        output.write_text(REPORT, encoding="utf-8")
        workflow_runtime.update_workflow_record(
            root,
            "wf-spawn",
            "research",
            "researcher",
            [],
            [],
            [],
            "run-1",
            root / "config.json",
            root / "status.json",
            output,
            root / "prompt.md",
            root / "stream.jsonl",
            root / "trace.log",
            "completed",
            codex_thread_id="agent-1",
        )
        path = workflow_runtime.workflow_path(root, "wf-spawn")

        assert load_json(path)["finalAcceptance"]["status"] == "pending-agent-spawn"

        workflow_runtime.record_agent_spawn(root, "wf-spawn", "research", "agent-1")
        assert load_json(path)["finalAcceptance"]["status"] == "pending-agent-close"

        workflow_runtime.record_agent_close(root, "wf-spawn", "research", "agent-1")
        assert load_json(path)["finalAcceptance"]["status"] == "accepted"


def test_canonical_spawn_handle_binds_to_child_thread_id() -> None:
    with tempfile.TemporaryDirectory(prefix="codex_with_cc_agent_alias_") as tmp:
        root = Path(tmp)
        output = root / "report.md"
        output.write_text(REPORT, encoding="utf-8")
        workflow_runtime.record_agent_spawn(root, "wf-alias", "research", "/root/research_task")
        workflow_runtime.update_workflow_record(
            root,
            "wf-alias",
            "research",
            "researcher",
            [],
            [],
            [],
            "run-1",
            root / "config.json",
            root / "status.json",
            output,
            root / "prompt.md",
            root / "stream.jsonl",
            root / "trace.log",
            "completed",
            codex_thread_id="019f-child-thread",
        )

        path = workflow_runtime.workflow_path(root, "wf-alias")
        workflow = load_json(path)
        assert set(workflow["agentAttempts"]) == {"/root/research_task"}
        attempt = workflow["agentAttempts"]["/root/research_task"]
        assert attempt["codexThreadId"] == "019f-child-thread"
        assert attempt["runId"] == "run-1"
        assert workflow["finalAcceptance"]["status"] == "pending-agent-close"

        workflow_runtime.record_agent_close(root, "wf-alias", "research", "/root/research_task")

        assert load_json(path)["finalAcceptance"]["status"] == "accepted"


def test_canonical_spawn_handle_can_close_by_child_thread_alias() -> None:
    with tempfile.TemporaryDirectory(prefix="codex_with_cc_agent_alias_close_") as tmp:
        root = Path(tmp)
        output = root / "report.md"
        output.write_text(REPORT, encoding="utf-8")
        workflow_runtime.record_agent_spawn(root, "wf-alias", "research", "/root/research_task")
        workflow_runtime.update_workflow_record(
            root,
            "wf-alias",
            "research",
            "researcher",
            [],
            [],
            [],
            "run-1",
            root / "config.json",
            root / "status.json",
            output,
            root / "prompt.md",
            root / "stream.jsonl",
            root / "trace.log",
            "completed",
            codex_thread_id="019f-child-thread",
        )

        workflow_runtime.record_agent_close(root, "wf-alias", "research", "019f-child-thread")

        path = workflow_runtime.workflow_path(root, "wf-alias")
        assert load_json(path)["finalAcceptance"]["status"] == "accepted"


def test_ambiguous_spawn_handles_do_not_guess_child_thread_alias() -> None:
    with tempfile.TemporaryDirectory(prefix="codex_with_cc_agent_alias_ambiguous_") as tmp:
        root = Path(tmp)
        output = root / "report.md"
        output.write_text(REPORT, encoding="utf-8")
        workflow_runtime.record_agent_spawn(root, "wf-alias", "research", "/root/research_a")
        workflow_runtime.record_agent_spawn(root, "wf-alias", "research", "/root/research_b")
        workflow_runtime.update_workflow_record(
            root,
            "wf-alias",
            "research",
            "researcher",
            [],
            [],
            [],
            "run-1",
            root / "config.json",
            root / "status.json",
            output,
            root / "prompt.md",
            root / "stream.jsonl",
            root / "trace.log",
            "completed",
            codex_thread_id="019f-child-thread",
        )

        workflow = load_json(workflow_runtime.workflow_path(root, "wf-alias"))
        assert "019f-child-thread" in workflow["agentAttempts"]
        assert workflow["finalAcceptance"]["status"] == "pending-agent-spawn"


def test_claude_cli_uses_role_routing_and_structured_output() -> None:
    args = new_claude_cli_args(
        "sonnet",
        "review-session",
        "reviewer",
        "session-id",
        False,
        "1.50",
        False,
    )

    assert args[args.index("--name") + 1] == "review-session"
    assert args[args.index("--effort") + 1] == "medium"
    assert "Agent" in args[args.index("--disallowed-tools") + 1]
    assert "Edit" in args[args.index("--disallowed-tools") + 1]
    assert "--json-schema" in args


def test_stream_capture_prefers_reported_cost_and_structured_result() -> None:
    state: dict = {}
    update_stream_capture(
        {
            "type": "result",
            "subtype": "success",
            "total_cost_usd": 0.42,
            "usage": {"input_tokens": 10, "output_tokens": 20},
            "structured_output": {
                "status": "DONE",
                "role": "researcher",
                "summary": "Checked the flow.",
                "changedFiles": [],
                "verification": ["pytest: passed"],
                "findings": [],
                "finalResult": "DONE",
                "risksOrFollowUps": [],
            },
        },
        state,
    )

    assert state["totalCostUsd"] == 0.42
    assert state["usage"]["input_tokens"] == 10
    assert state["capturedFinalResultHeading"] is True
    assert state["finalText"].startswith("Status\nDONE\n")


@pytest.mark.parametrize(
    ("script", "task_goal"),
    [
        ("#!/bin/sh\nsleep 30\n", "x" * 1_000_000),
        ("#!/bin/sh\ncat >/dev/null\nexec 1>&-\nsleep 30\n", "exercise closed stdout timeout"),
    ],
)
def test_watchdog_covers_blocked_stdin_and_stdout_eof(script: str, task_goal: str) -> None:
    with tempfile.TemporaryDirectory(prefix="codex_with_cc_watchdog_edges_") as tmp:
        root = Path(tmp)
        bin_dir = root / "bin"
        artifact_root = root / "artifacts"
        bin_dir.mkdir()
        fake_claude = bin_dir / "claude"
        fake_claude.write_text(script, encoding="utf-8")
        fake_claude.chmod(0o755)
        task_file = root / "task.md"
        task_file.write_text(compliant_task(task_goal), encoding="utf-8")

        started = time.monotonic()
        result = run_python(
            DELEGATE,
            "-TaskFile",
            str(task_file),
            "-WorkflowId",
            "wf-watchdog",
            "-TaskId",
            "research",
            "-Role",
            "researcher",
            "-SessionKey",
            "wf-watchdog",
            "-ArtifactRoot",
            str(artifact_root),
            "-SilentTimeoutSeconds",
            "1",
            "-ExecutionTimeoutSeconds",
            "10",
            "-HeartbeatSeconds",
            "1",
            "-MaxRetryCount",
            "0",
            "-TrustedLocalFallback",
            env_extra={"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"},
        )

        assert result.returncode != 0
        assert time.monotonic() - started < 8
        status = load_json(next(artifact_root.glob("status_*.json")))
        assert status["timeoutKind"] == "silent"
