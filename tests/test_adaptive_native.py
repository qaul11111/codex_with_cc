"""Offline fixtures for admission, evidence and acceptance; no model is invoked."""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "skills/codex-native-agents/scripts")
)
from codex_native_agents_runtime import evidence, planning, workflow as w
from codex_native_agents_runtime.cli import main
from tests.task_helpers import compliant_native_task, compliant_native_report
from tests.test_native_hooks import task_envelope
from tests.test_native_workflow import (
    ready_for_acceptance_workflow,
    record_spawn_for_task,
    close_task,
)


@pytest.fixture
def managed(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    (project / "app.py").write_text("value=1\n")
    root = project / ".evidence"
    root.mkdir()
    home = tmp_path / "home"
    (home / "sessions").mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("CODEX_THREAD_ID", "main")
    meta = {
        "type": "session_meta",
        "payload": {"id": "main", "cwd": str(project), "source": "cli"},
    }
    (home / "sessions/rollout-main.jsonl").write_text(json.dumps(meta) + "\n")
    caps = {
        "source": "active-tool-catalog",
        "tools": ["spawn_agent", "list_agents", "wait_agent"],
        "forkParameter": "fork_turns",
        "models": {"gpt-6-astra": ["low", "medium", "high", "xhigh"]},
        "maxAgents": 3,
        "lifecycle": "terminal-evidence",
    }
    flow = w.new_workflow(
        "adaptive",
        project_root=project,
        artifact_root=root,
        profile="standard",
        host=caps,
    )
    return flow, project, root, home


def register(
    managed,
    task_id="work",
    role="implementer",
    scopes=("app.py",),
    writable=True,
    **kwargs
):
    flow, project, root, home = managed
    task = root / (task_id + ".md")
    task.write_text(compliant_native_task())
    return w.register_task(
        flow,
        task_id=task_id,
        role=role,
        scopes=scopes,
        writable=writable,
        task_file=task,
        **kwargs
    )


def transcript(managed, task_id, agent, *, effort=None, aborted=False):
    flow, project, root, home = managed
    task = flow["tasks"][task_id]
    now = datetime.now(timezone.utc).isoformat()
    report = compliant_native_report("DONE", task["role"])
    rows = [
        {
            "type": "session_meta",
            "payload": {"id": agent, "cwd": str(project), "parent_thread_id": "main"},
        },
        {
            "type": "event_msg",
            "timestamp": now,
            "payload": {"type": "task_started", "turn_id": "one"},
        },
        {
            "type": "turn_context",
            "payload": {
                "model": "gpt-6-astra",
                "effort": effort or task["reasoningEffort"],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
                "content": [{"type": "output_text", "text": report}],
            },
        },
        {
            "type": "event_msg",
            "timestamp": now,
            "payload": {
                "type": "turn_aborted" if aborted else "task_complete",
                "turn_id": "one",
            },
        },
    ]
    path = home / "sessions" / ("rollout-" + agent + ".jsonl")
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path, report


def finish(managed, task_id="work", agent="agent"):
    flow = managed[0]
    planning.prepare_spawn(flow, task_id)
    w.record_spawn(flow, task_id=task_id, agent_id=agent, actual_model="gpt-6-astra")
    path, report = transcript(managed, task_id, agent)
    w.record_run(
        flow, task_id=task_id, agent_id=agent, report=report, transcript_path=path
    )
    w.record_close(
        flow,
        task_id=task_id,
        agent_id=agent,
        status="unsupported",
        transcript_path=path,
    )
    return path


def test_current_host_fork_turns_and_conflicting_context():
    hook = Path(__file__).resolve().parents[1] / "hooks/native-agent-gate-hook.mjs"
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "collaboration.spawn_agent",
        "tool_input": {
            "message": task_envelope(),
            "fork_turns": "none",
            "model": "gpt-6-astra",
            "reasoning_effort": "medium",
        },
    }

    def result():
        run = subprocess.run(
            ["node", str(hook)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(run.stdout or "{}")

    assert result() == {}
    payload["tool_input"]["fork_context"] = True
    assert result()["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_empty_workflow_rejected():
    with pytest.raises(w.WorkflowError, match="Empty"):
        w.verify_workflow(w.new_workflow("empty"))


def test_late_old_review_cannot_bind_new_implementation():
    flow = ready_for_acceptance_workflow()
    record_spawn_for_task(flow, "spec-review", "old-review")
    record_spawn_for_task(flow, "impl", "new-impl")
    w.record_run(
        flow,
        task_id="impl",
        agent_id="new-impl",
        report=compliant_native_report("DONE", "implementer"),
    )
    with pytest.raises(w.WorkflowError, match="target changed"):
        w.record_run(
            flow,
            task_id="spec-review",
            agent_id="old-review",
            report=compliant_native_report("DONE", "reviewer"),
        )


def test_final_snapshot_is_fixed_at_dispatch():
    flow = ready_for_acceptance_workflow()
    record_spawn_for_task(flow, "final", "early-final")
    record_spawn_for_task(flow, "spec-review", "new-review")
    w.record_run(
        flow,
        task_id="spec-review",
        agent_id="new-review",
        report=compliant_native_report("DONE", "reviewer"),
    )
    close_task(flow, "spec-review")
    w.record_run(
        flow,
        task_id="final",
        agent_id="early-final",
        report=compliant_native_report("DONE", "final-verifier"),
    )
    close_task(flow, "final")
    with pytest.raises(w.WorkflowError, match="snapshot is stale"):
        w.verify_workflow(flow)


@pytest.mark.parametrize(
    "complexity,independent,coupled,minutes,execution",
    [
        ("simple", True, False, 10, "main"),
        ("complex", True, True, 30, "main"),
        ("normal", False, False, 20, "main"),
        ("normal", True, False, 1, "main"),
        ("complex", True, False, 20, "native"),
    ],
)
def test_task_shape_drives_delegation(
    complexity, independent, coupled, minutes, execution
):
    assert (
        planning.advise(
            complexity=complexity,
            independent=independent,
            coupled=coupled,
            estimated_minutes=minutes,
            overhead_minutes=2,
        )["execution"]
        == execution
    )


def test_admission_serializes_read_write_conflicts_and_dependencies(managed):
    register(managed, "a", parallel=True)
    register(managed, "b", role="researcher", writable=False, parallel=True)
    register(managed, "c", scopes=("other.py",), parallel=True, depends_on=["a"])
    assert planning.ready_tasks(managed[0])["ready"] == ["a"]
    planning.prepare_spawn(managed[0], "a")
    with pytest.raises(ValueError, match="active scope"):
        planning.prepare_spawn(managed[0], "b")
    with pytest.raises(ValueError, match="dependency"):
        planning.prepare_spawn(managed[0], "c")


def test_independent_read_tasks_fill_only_available_slots(managed):
    managed[0]["policy"]["host"]["maxAgents"] = 2
    for name in ["a", "b", "c"]:
        register(managed, name, role="researcher", writable=False, parallel=True)
    assert planning.ready_tasks(managed[0])["ready"] == ["a", "b"]


def test_main_reserved_scope_and_unsupported_effort_block_dispatch(managed):
    register(managed)
    managed[0]["policy"]["mainScopes"] = ["app.py"]
    with pytest.raises(ValueError, match="main-thread"):
        planning.prepare_spawn(managed[0], "work")
    managed[0]["policy"]["mainScopes"] = []
    managed[0]["policy"]["host"]["models"]["gpt-6-astra"] = ["low"]
    with pytest.raises(ValueError, match="effort unavailable"):
        planning.prepare_spawn(managed[0], "work")


def test_standard_requires_real_checks_main_review_and_current_source(managed):
    flow, project, root, home = managed
    register(managed)
    finish(managed)
    with pytest.raises(ValueError, match="executed checks"):
        w.verify_workflow(flow)
    w.write_workflow(root, flow)
    checks = root / "checks.json"
    checks.write_text(
        json.dumps(
            {
                "checks": [
                    {
                        "argv": [
                            sys.executable,
                            "-c",
                            "from pathlib import Path; assert 'value=1' in Path('app.py').read_text()",
                        ]
                    }
                ]
            }
        )
    )
    review = root / "review.md"
    review.write_text(
        "Scope: app.py. Quality: verified value. Risks: offline fixture only."
    )
    prefix = ["--artifact-root", str(root)]
    assert (
        main(
            prefix
            + ["run-checks", "--workflow-id", "adaptive", "--checks-file", str(checks)]
        )
        == 0
    )
    assert (
        main(
            prefix
            + [
                "record-main-review",
                "--workflow-id",
                "adaptive",
                "--review-file",
                str(review),
            ]
        )
        == 0
    )
    assert main(prefix + ["verify", "--workflow-id", "adaptive"]) == 0
    flow = w.load_workflow(root, "adaptive")
    assert flow["status"] == "accepted"
    assert flow["tasks"]["work"]["latestClose"]["closeStatus"] == "unsupported"
    (project / "app.py").write_text("value=2\n")
    with pytest.raises(ValueError, match="stale"):
        w.verify_workflow(flow)


def test_actual_effort_mismatch_and_aborted_completion_rejected(managed):
    flow = managed[0]
    register(managed)
    planning.prepare_spawn(flow, "work")
    w.record_spawn(flow, task_id="work", agent_id="agent", actual_model="gpt-6-astra")
    path, report = transcript(managed, "work", "agent", effort="low")
    with pytest.raises(ValueError, match="reasoning effort"):
        w.record_run(
            flow, task_id="work", agent_id="agent", report=report, transcript_path=path
        )
    path, report = transcript(managed, "work", "agent", aborted=True)
    with pytest.raises(ValueError, match="original host final"):
        w.record_run(
            flow, task_id="work", agent_id="agent", report=report, transcript_path=path
        )
    w.record_close(
        flow,
        task_id="work",
        agent_id="agent",
        status="unsupported",
        transcript_path=path,
    )
    assert flow["tasks"]["work"]["latestClose"]["runId"] is None


def test_false_closed_claim_and_changed_host_log_rejected(managed):
    flow = managed[0]
    register(managed)
    path = finish(managed)
    saved = flow["tasks"]["work"]["latestClose"]["terminalEvidence"]
    path.write_text(path.read_text().replace("gpt-6-astra", "other-model"))
    with pytest.raises(ValueError, match="evidence changed"):
        evidence.recheck_terminal(saved, flow["policy"]["projectRoot"])


def test_non_astra_fallback_and_missing_preparation_rejected(managed):
    flow = managed[0]
    register(managed)
    with pytest.raises(ValueError, match="prepare-spawn"):
        w.record_spawn(flow, task_id="work", agent_id="a", actual_model="gpt-6-astra")
    planning.prepare_spawn(flow, "work")
    with pytest.raises(ValueError, match="Astra-only"):
        w.record_spawn(
            flow,
            task_id="work",
            agent_id="a",
            actual_model="gpt-5.6-sol",
            fallback_reason="unavailable",
        )


def test_strict_lifecycle_does_not_accept_a_typed_close_claim(managed):
    flow = managed[0]
    flow["policy"]["host"]["lifecycle"] = "strict-close"
    register(managed)
    planning.prepare_spawn(flow, "work")
    w.record_spawn(flow, task_id="work", agent_id="agent", actual_model="gpt-6-astra")
    path, report = transcript(managed, "work", "agent")
    with pytest.raises(ValueError, match="close_agent result"):
        w.record_close(
            flow,
            task_id="work",
            agent_id="agent",
            status="closed",
            transcript_path=path,
        )


def test_high_risk_cannot_use_standard(managed):
    with pytest.raises(ValueError, match="strict workflow"):
        register(managed, complexity="high-risk")


def test_failed_check_invalidates_previous_success(managed):
    flow, project, root, home = managed
    register(managed)
    finish(managed)
    w.write_workflow(root, flow)
    path = root / "checks.json"
    prefix = [
        "--artifact-root",
        str(root),
        "run-checks",
        "--workflow-id",
        "adaptive",
        "--checks-file",
        str(path),
    ]
    path.write_text(json.dumps({"checks": [{"argv": [sys.executable, "-c", "pass"]}]}))
    assert main(prefix) == 0
    path.write_text(
        json.dumps(
            {"checks": [{"argv": [sys.executable, "-c", "raise SystemExit(3)"]}]}
        )
    )
    with pytest.raises(SystemExit):
        main(prefix)
    assert not w.load_workflow(root, "adaptive").get("checkEvidence")


def test_terminal_prefix_tolerates_unrelated_append_but_not_new_turn(managed):
    flow = managed[0]
    register(managed)
    path = finish(managed)
    saved = flow["tasks"]["work"]["latestClose"]["terminalEvidence"]
    with path.open("a") as handle:
        handle.write(
            json.dumps({"type": "event_msg", "payload": {"type": "token_count"}}) + "\n"
        )
    evidence.recheck_terminal(saved, flow["policy"]["projectRoot"])
    with path.open("a") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "event_msg",
                    "payload": {"type": "task_started", "turn_id": "new"},
                }
            )
            + "\n"
        )
    with pytest.raises(ValueError, match="terminal host turn"):
        evidence.recheck_terminal(saved, flow["policy"]["projectRoot"])


def test_retry_escalates_effort_once_and_gets_unique_task_name(managed):
    flow = managed[0]
    register(managed)
    first = planning.prepare_spawn(flow, "work")
    w.record_spawn(flow, task_id="work", agent_id="a", actual_model="gpt-6-astra")
    path, _ = transcript(managed, "work", "a", aborted=True)
    w.record_close(
        flow, task_id="work", agent_id="a", status="unsupported", transcript_path=path
    )
    second = planning.prepare_spawn(flow, "work", escalate=True)
    assert second["task_name"] != first["task_name"]
    assert (
        first["reasoning_effort"] == "medium" and second["reasoning_effort"] == "high"
    )
    w.record_spawn(flow, task_id="work", agent_id="b", actual_model="gpt-6-astra")
    path, _ = transcript(managed, "work", "b", aborted=True)
    w.record_close(
        flow, task_id="work", agent_id="b", status="unsupported", transcript_path=path
    )
    with pytest.raises(ValueError, match="Retry budget"):
        planning.prepare_spawn(flow, "work", escalate=True)


def test_close_agent_receipt_binds_original_parent_and_child(managed):
    flow, project, root, home = managed
    flow["policy"]["host"]["lifecycle"] = "strict-close"
    register(managed)
    planning.prepare_spawn(flow, "work")
    w.record_spawn(flow, task_id="work", agent_id="agent", actual_model="gpt-6-astra")
    path, report = transcript(managed, "work", "agent")
    w.record_run(
        flow, task_id="work", agent_id="agent", report=report, transcript_path=path
    )
    parent = home / "sessions/rollout-main.jsonl"
    now = datetime.now(timezone.utc).isoformat()
    with parent.open("a") as handle:
        handle.write(
            json.dumps(
                {
                    "timestamp": now,
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "close_agent",
                        "call_id": "close",
                        "arguments": json.dumps({"agent_id": "agent"}),
                    },
                }
            )
            + "\n"
        )
        handle.write(
            json.dumps(
                {
                    "timestamp": now,
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "close",
                        "output": json.dumps({"status": "completed"}),
                    },
                }
            )
            + "\n"
        )
    result = w.record_close(
        flow,
        task_id="work",
        agent_id="agent",
        status="closed",
        transcript_path=path,
        close_transcript=parent,
    )
    assert result["closeStatus"] == "closed" and result["closeEvidence"]["records"]


def test_strict_managed_workflow_accepts_only_current_final_source(managed):
    flow, project, root, home = managed
    flow["policy"]["profile"] = "strict"
    register(managed)
    finish(managed)
    for kind in ["spec", "quality"]:
        register(
            managed,
            kind,
            role="reviewer",
            writable=False,
            review_for_task_id="work",
            review_kind=kind,
        )
        finish(managed, kind, kind + "-agent")
    register(managed, "final", role="final-verifier", writable=False)
    finish(managed, "final", "final-agent")
    w.verify_workflow(flow)
    (project / "app.py").write_text("changed after final\n")
    with pytest.raises(ValueError, match="source snapshot is stale"):
        w.verify_workflow(flow)


def test_scope_aliases_share_ownership_and_outside_links_are_rejected(managed):
    flow, project, root, home = managed
    (project / "src").mkdir()
    (project / "alias").symlink_to(project / "src", target_is_directory=True)
    register(managed, "one", scopes=("src/file.py",), parallel=True)
    with pytest.raises(ValueError, match="overlap"):
        register(managed, "two", scopes=("alias/file.py",), parallel=True)
    (project / "outside").symlink_to(home, target_is_directory=True)
    with pytest.raises(ValueError, match="outside the project"):
        register(managed, "bad", scopes=("outside/file.py",))


def test_readers_cannot_overlap_main_owned_writes(managed):
    flow = managed[0]
    flow["policy"]["mainScopes"] = ["app.py"]
    register(managed, role="researcher", writable=False)
    with pytest.raises(ValueError, match="main-thread"):
        planning.prepare_spawn(flow, "work")
