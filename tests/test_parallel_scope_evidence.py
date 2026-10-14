"""Offline fixtures only: no model calls and no fabricated production evidence.

Serial historical retries of the SAME implementer TaskId share scope by
definition; the parallel-scope gate must not confuse them with concurrent
overlapping writes, but ONLY when per-run pinned terminal evidence is present,
re-verified against the untouched originals, and proves serial execution.
Every artifact here is synthetic under tmp_path with fake Codex rollouts under
a fake CODEX_HOME; nothing touches real workflow artifacts.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "codex-with-cc" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from codex_with_cc_runtime import artifacts
from codex_with_cc_runtime import lifecycle
from codex_with_cc_runtime import workflow as wf
from codex_with_cc_runtime.common import (
    ARTIFACT_SCHEMA_VERSION,
    CHILD_MARKER_NAME,
    INVOCATION_CONTRACT,
    DelegateError,
)
from codex_with_cc_runtime.io_utils import load_json

TASK = "foundation"
WF = "wf-parallel-scope"
OLD_RUN = "20260904_160000_000_aaaa0001"
NEW_RUN = "20260904_170000_000_bbbb0002"
THREAD_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
THREAD_B = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
HANDLE_A = "/root/parallel_a"
HANDLE_B = "/root/parallel_b"
PARENT = "cccccccc-3333-4333-8333-cccccccccccc"
SCOPE = ["knowledge/platforms/android-native"]

# Serial timing: earlier runner completes at 10:29:00Z (pinned status
# updatedAt), later host turn starts 10:35:00Z. The earlier host relay ends
# 10:30:00Z; ordering never relies on host terminalAt.
A_START, A_END, A_STATUS = "2026-09-04T10:00:00Z", "2026-09-04T10:30:00Z", "2026-09-04T10:29:00+00:00"
B_START, B_END, B_STATUS = "2026-09-04T10:35:00Z", "2026-09-04T10:40:00Z", "2026-09-04T10:39:00+00:00"
# Overlapping variant: later host turn starts before the earlier runner ended.
B_OVERLAP_START = "2026-09-04T10:25:00Z"

IMPL_REPORT = """Status
DONE

Role
implementer

Summary
Offline fixture implementation.

Changed Files
- knowledge/platforms/android-native/INDEX.md

Verification
- offline fixture verification passed

Findings
- offline fixture

Final Result
DONE

Risks Or Follow-ups
- offline fixture only
"""

REVIEW_REPORT = IMPL_REPORT.replace("implementer", "reviewer")


def save(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def rollout_text(thread: str, handle: str, cwd: Path, started: str, terminal: str) -> str:
    records = [
        {
            "type": "session_meta",
            "payload": {
                "id": thread,
                "cwd": str(cwd),
                "source": {"subagent": {"thread_spawn": {"parent_thread_id": PARENT, "agent_path": handle}}},
            },
        },
        {"type": "event_msg", "timestamp": started, "payload": {"type": "task_started", "turn_id": f"{thread}-turn"}},
        {"type": "event_msg", "timestamp": terminal, "payload": {"type": "task_complete", "turn_id": f"{thread}-turn"}},
    ]
    return "".join(json.dumps(record) + "\n" for record in records)


def write_run_files(
    root: Path,
    repo: Path,
    run_id: str,
    *,
    task: str = TASK,
    role: str = "implementer",
    report: str = IMPL_REPORT,
    scope=SCOPE,
    allow_parallel: bool = True,
    status_updated_at: str = A_STATUS,
    thread: str = THREAD_A,
    reviewer_binding: dict | None = None,
) -> None:
    report_path = root / f"claude_{run_id}.md"
    report_path.write_text(report, encoding="utf-8")
    stream = root / f"stream_{run_id}.jsonl"
    stream.write_text("", encoding="utf-8")
    common = {
        "artifactSchema": ARTIFACT_SCHEMA_VERSION,
        "invocationContract": INVOCATION_CONTRACT,
        "childThreadMarkerName": CHILD_MARKER_NAME,
        "childThreadMarkerValidated": True,
        "workflowId": WF,
        "taskId": task,
        "runId": run_id,
        "role": role,
        "codexThreadId": thread,
        "outputPath": str(report_path),
        "exitCode": 0,
        "attemptCount": 1,
        "retryCount": 0,
        "runnerType": "claude_code",
        "tests": [],
        "rawStreamPath": str(stream),
    }
    config = {
        **common,
        "repoRoot": str(repo),
        "sessionMode": "ParallelPool",
        "sessionKey": "parallel-scope",
        "initialSessionId": f"session-{run_id}",
        "initialResume": False,
        "sessionId": f"session-{run_id}",
        "resume": False,
        "dryRun": False,
        "trustedLocalFallback": False,
        "allowParallel": allow_parallel,
        "scope": list(scope),
        "sessionStatePath": str(root / f"session_{run_id}.json"),
        "statusPath": str(root / f"status_{run_id}.json"),
    }
    if reviewer_binding:
        config.update(reviewer_binding)
    status = {
        **common,
        "status": "completed",
        "pid": 424242,
        "updatedAt": status_updated_at,
        "attempts": [
            {
                "attempt": 1,
                "sessionId": f"session-{run_id}",
                "resume": False,
                "retryReason": None,
                "exitCode": 0,
                "sawAssistantText": True,
                "sawResultSuccess": True,
                "capturedFinalResult": True,
            }
        ],
    }
    save(root / f"config_{run_id}.json", config)
    save(root / f"status_{run_id}.json", status)
    save(root / f"session_{run_id}.json", {"parallelPool": []})


@pytest.fixture
def serial_env(tmp_path, monkeypatch):
    """Two settled serial implementer runs of the same task with terminal proof."""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    sessions = lifecycle.sessions_root()
    sessions.mkdir(parents=True)
    def dead_pid(pid, sig):
        raise ProcessLookupError(pid)
    monkeypatch.setattr(lifecycle.os, "kill", dead_pid)
    root = tmp_path / "artifacts"
    root.mkdir()
    caps = tmp_path / "tools.json"
    save(
        caps,
        {
            "schemaVersion": 1,
            "source": "active-tool-catalog",
            "tools": ["collaboration.spawn_agent", "collaboration.wait_agent", "collaboration.list_agents"],
        },
    )
    lifecycle.configure_lifecycle(root, WF, "terminal-evidence", caps)
    return root, sessions, tmp_path


def add_implementer_run(
    root: Path,
    sessions: Path,
    repo: Path,
    run_id: str,
    thread: str,
    handle: str,
    *,
    turn_start: str,
    turn_end: str,
    status_updated_at: str,
    scope=SCOPE,
    task: str = TASK,
    settle: bool = True,
) -> Path:
    write_run_files(root, repo, run_id, task=task, scope=scope, status_updated_at=status_updated_at, thread=thread)
    wf.record_agent_spawn(root, WF, task, handle)
    wf.update_workflow_record(
        root,
        WF,
        task,
        "implementer",
        list(scope),
        [],
        [],
        run_id,
        root / f"config_{run_id}.json",
        root / f"status_{run_id}.json",
        root / f"claude_{run_id}.md",
        root / f"prompt_{run_id}.md",
        root / f"stream_{run_id}.jsonl",
        root / f"trace_{run_id}.log",
        "completed",
        codex_thread_id=thread,
    )
    rollout = sessions / f"rollout-2026-09-04T10-00-00-{thread}.jsonl"
    rollout.write_text(rollout_text(thread, handle, repo, turn_start, turn_end), encoding="utf-8")
    if settle:
        lifecycle.record_agent_terminal(root, WF, task, handle, rollout)
    return rollout


def gate(root: Path) -> None:
    workflow = load_json(wf.workflow_path(root, WF))
    records = {
        run_id: artifacts.verify_artifacts(run_id, str(root), recover_status=False)
        for run_id in (workflow.get("runs") or {})
    }
    artifacts.enforce_parallel_implementer_scope(workflow, records)


def add_reviews(root: Path, repo: Path, review_for: str) -> None:
    for kind in ("spec", "quality"):
        review_run = f"20260904_1800{0 if kind == 'spec' else 1}0_000_{kind}0000aa"
        write_run_files(
            root,
            repo,
            review_run,
            task=f"{TASK}-{kind}",
            role="reviewer",
            report=REVIEW_REPORT,
            allow_parallel=False,
            scope=[],
            thread=f"dddddddd-{kind}-4333-8333-dddddddddddd",
            reviewer_binding={"reviewForTaskId": TASK, "reviewForRunId": review_for, "reviewKind": kind},
        )
        wf.update_workflow_record(
            root,
            WF,
            f"{TASK}-{kind}",
            "reviewer",
            [],
            [],
            [],
            review_run,
            root / f"config_{review_run}.json",
            root / f"status_{review_run}.json",
            root / f"claude_{review_run}.md",
            root / f"prompt_{review_run}.md",
            root / f"stream_{review_run}.jsonl",
            root / f"trace_{review_run}.log",
            "completed",
            review_for_task_id=TASK,
            review_for_run_id=review_for,
            review_kind=kind,
        )


def test_serial_same_task_retries_with_reverified_proof_pass(serial_env):
    root, sessions, repo = serial_env
    add_implementer_run(root, sessions, repo, OLD_RUN, THREAD_A, HANDLE_A,
                        turn_start=A_START, turn_end=A_END, status_updated_at=A_STATUS)
    add_implementer_run(root, sessions, repo, NEW_RUN, THREAD_B, HANDLE_B,
                        turn_start=B_START, turn_end=B_END, status_updated_at=B_STATUS)
    gate(root)


def test_overlap_same_task_rejected_with_task_and_run_ids(serial_env):
    root, sessions, repo = serial_env
    add_implementer_run(root, sessions, repo, OLD_RUN, THREAD_A, HANDLE_A,
                        turn_start=A_START, turn_end=A_END, status_updated_at=A_STATUS)
    add_implementer_run(root, sessions, repo, NEW_RUN, THREAD_B, HANDLE_B,
                        turn_start=B_OVERLAP_START, turn_end=B_END, status_updated_at=B_STATUS)
    with pytest.raises(DelegateError) as excinfo:
        gate(root)
    message = str(excinfo.value)
    assert "overlapping parallel implementer scope" in message
    assert TASK in message
    assert OLD_RUN in message
    assert NEW_RUN in message


def test_distinct_task_overlap_still_rejected(serial_env):
    root, sessions, repo = serial_env
    add_implementer_run(root, sessions, repo, OLD_RUN, THREAD_A, HANDLE_A,
                        turn_start=A_START, turn_end=A_END, status_updated_at=A_STATUS)
    add_implementer_run(root, sessions, repo, NEW_RUN, THREAD_B, HANDLE_B,
                        turn_start=B_START, turn_end=B_END, status_updated_at=B_STATUS, task="other-task")
    with pytest.raises(DelegateError, match="overlapping parallel implementer scope"):
        gate(root)


def test_missing_terminal_evidence_rejected(serial_env):
    root, sessions, repo = serial_env
    add_implementer_run(root, sessions, repo, OLD_RUN, THREAD_A, HANDLE_A,
                        turn_start=A_START, turn_end=A_END, status_updated_at=A_STATUS, settle=False)
    add_implementer_run(root, sessions, repo, NEW_RUN, THREAD_B, HANDLE_B,
                        turn_start=B_START, turn_end=B_END, status_updated_at=B_STATUS)
    with pytest.raises(DelegateError, match="overlapping parallel implementer scope"):
        gate(root)


def test_forged_stored_evidence_rejected(serial_env):
    root, sessions, repo = serial_env
    add_implementer_run(root, sessions, repo, OLD_RUN, THREAD_A, HANDLE_A,
                        turn_start=A_START, turn_end=A_END, status_updated_at=A_STATUS)
    add_implementer_run(root, sessions, repo, NEW_RUN, THREAD_B, HANDLE_B,
                        turn_start=B_START, turn_end=B_END, status_updated_at=B_STATUS)
    path = wf.workflow_path(root, WF)
    workflow = load_json(path)
    workflow["agentAttempts"][HANDLE_A]["executionEvidence"]["host"]["terminalAt"] = "2026-09-04T10:05:00Z"
    save(path, workflow)
    with pytest.raises(DelegateError, match="overlapping parallel implementer scope"):
        gate(root)


def test_changed_transcript_rejected(serial_env):
    root, sessions, repo = serial_env
    add_implementer_run(root, sessions, repo, OLD_RUN, THREAD_A, HANDLE_A,
                        turn_start=A_START, turn_end=A_END, status_updated_at=A_STATUS)
    rollout = add_implementer_run(root, sessions, repo, NEW_RUN, THREAD_B, HANDLE_B,
                                  turn_start=B_START, turn_end=B_END, status_updated_at=B_STATUS)
    with rollout.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"type": "event_msg", "timestamp": B_END,
                                 "payload": {"type": "token_count", "info": None}}) + "\n")
    with pytest.raises(DelegateError, match="overlapping parallel implementer scope"):
        gate(root)


def test_naive_or_malformed_time_rejected(serial_env):
    root, sessions, repo = serial_env
    add_implementer_run(root, sessions, repo, OLD_RUN, THREAD_A, HANDLE_A,
                        turn_start=A_START, turn_end=A_END, status_updated_at=A_STATUS)
    add_implementer_run(root, sessions, repo, NEW_RUN, THREAD_B, HANDLE_B,
                        turn_start=B_START, turn_end=B_END, status_updated_at=B_STATUS)
    status_path = root / f"status_{OLD_RUN}.json"
    status = load_json(status_path)
    status["updatedAt"] = "2026-09-04T10:29:00"  # naive: no timezone
    save(status_path, status)
    with pytest.raises(DelegateError, match="overlapping parallel implementer scope"):
        gate(root)


def test_runner_completion_outside_host_turn_rejected(serial_env):
    root, sessions, repo = serial_env
    add_implementer_run(root, sessions, repo, OLD_RUN, THREAD_A, HANDLE_A,
                        turn_start=A_START, turn_end=A_END, status_updated_at=A_STATUS)
    add_implementer_run(root, sessions, repo, NEW_RUN, THREAD_B, HANDLE_B,
                        turn_start=B_START, turn_end=B_END, status_updated_at=B_STATUS)
    status_path = root / f"status_{OLD_RUN}.json"
    status = load_json(status_path)
    status["updatedAt"] = "2026-09-04T10:31:00+00:00"  # after the host terminalAt
    save(status_path, status)
    with pytest.raises(DelegateError, match="overlapping parallel implementer scope"):
        gate(root)


def test_duplicate_attempt_binding_rejected(serial_env):
    root, sessions, repo = serial_env
    add_implementer_run(root, sessions, repo, OLD_RUN, THREAD_A, HANDLE_A,
                        turn_start=A_START, turn_end=A_END, status_updated_at=A_STATUS)
    add_implementer_run(root, sessions, repo, NEW_RUN, THREAD_B, HANDLE_B,
                        turn_start=B_START, turn_end=B_END, status_updated_at=B_STATUS)
    path = wf.workflow_path(root, WF)
    workflow = load_json(path)
    duplicate = dict(workflow["agentAttempts"][HANDLE_A])
    workflow["agentAttempts"]["/root/parallel_a_copy"] = duplicate
    save(path, workflow)
    with pytest.raises(DelegateError, match="overlapping parallel implementer scope"):
        gate(root)


def test_missing_scope_still_rejected(serial_env):
    root, sessions, repo = serial_env
    add_implementer_run(root, sessions, repo, OLD_RUN, THREAD_A, HANDLE_A,
                        turn_start=A_START, turn_end=A_END, status_updated_at=A_STATUS, scope=[])
    with pytest.raises(DelegateError, match="missing scope"):
        gate(root)


def test_dry_run_run_is_not_serial_evidence(serial_env):
    root, sessions, repo = serial_env
    add_implementer_run(root, sessions, repo, OLD_RUN, THREAD_A, HANDLE_A,
                        turn_start=A_START, turn_end=A_END, status_updated_at=A_STATUS)
    add_implementer_run(root, sessions, repo, NEW_RUN, THREAD_B, HANDLE_B,
                        turn_start=B_START, turn_end=B_END, status_updated_at=B_STATUS)
    config_path = root / f"config_{OLD_RUN}.json"
    config = load_json(config_path)
    config["dryRun"] = True
    save(config_path, config)
    with pytest.raises(DelegateError, match="overlapping parallel implementer scope"):
        gate(root)


def test_final_inputs_pass_with_inflight_unrelated_final_agent(serial_env):
    root, sessions, repo = serial_env
    add_implementer_run(root, sessions, repo, OLD_RUN, THREAD_A, HANDLE_A,
                        turn_start=A_START, turn_end=A_END, status_updated_at=A_STATUS)
    add_implementer_run(root, sessions, repo, NEW_RUN, THREAD_B, HANDLE_B,
                        turn_start=B_START, turn_end=B_END, status_updated_at=B_STATUS)
    add_reviews(root, repo, NEW_RUN)
    # An unrelated final-verifier agent is still running: spawned, no run, unsettled.
    wf.record_agent_spawn(root, WF, "final", "/root/final_inflight")
    result = artifacts.run_verify_final_inputs(argparse.Namespace(workflow_id=WF, artifact_root=str(root)))
    assert result == 0
