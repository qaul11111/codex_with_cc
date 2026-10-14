"""Offline end-to-end fixtures; these are not production host acceptance records."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/codex-with-cc/scripts"))
from codex_with_cc_runtime import artifacts, lifecycle, workflow
from codex_with_cc_runtime.cli import build_parser
from codex_with_cc_runtime.common import DelegateError
from codex_with_cc_runtime.io_utils import load_json
from tests.task_helpers import compliant_task
from tests.test_workflow_contract import workflow_report
from tests.test_platform_hooks import run_hook


def run(*args):
    ns = build_parser().parse_args(list(args))
    return ns.func(ns)


@pytest.fixture
def project(tmp_path, monkeypatch):
    p = tmp_path / "project"
    p.mkdir()
    subprocess.run(["git", "init", "-q", str(p)], check=True)
    (p / "app.py").write_text("value = 1\n")
    root = p / ".codex/codex_with_cc/claude-delegate"
    root.mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "home"))
    lifecycle.sessions_root().mkdir(parents=True)
    caps = tmp_path / "caps.json"
    caps.write_text(json.dumps({"schemaVersion": 1, "source": "active-tool-catalog", "tools": ["spawn_agent", "wait_agent", "list_agents"]}))
    run("configure-workflow", "-WorkflowId", "new", "-ProjectRoot", str(p), "-ArtifactRoot", str(root), "-Profile", "standard")
    lifecycle.configure_lifecycle(root, "new", "terminal-evidence", caps)
    return p, root


def prepare(project, backend="codex-native", role="implementer"):
    p, root = project
    task = root / "input-task.md"
    task.write_text(compliant_task("Verify the value in app.py and return the report."))
    run("prepare-task", "-WorkflowId", "new", "-TaskId", "impl", "-Backend", backend, "-Role", role,
        "-ArtifactRoot", str(root), "-TaskFile", str(task), "-Scope", "app.py")
    w = load_json(workflow.workflow_path(root, "new"))
    return Path(list(w["preparedTasks"].values())[-1]["path"])


def native_complete(project, monkeypatch, plan_path, *, aborted=False, report=None, actual_effort=None):
    p, root = project
    plan = load_json(plan_path)
    count = len(load_json(workflow.workflow_path(root, "new"))["agentAttempts"]) + 1
    thread = f"00000000-0000-0000-0000-{count:012d}"
    agent = f"/root/fixture{count}"
    workflow.record_agent_spawn(root, "new", plan["taskId"], agent)
    log = lifecycle.sessions_root() / f"rollout-{thread}.jsonl"
    start = plan["createdAt"]
    from codex_with_cc_runtime.common import now_iso
    end = now_iso()
    records = [
        {"type": "session_meta", "payload": {"id": thread, "cwd": str(p), "source": {"subagent": {"thread_spawn": {"parent_thread_id": "main", "agent_path": agent}}}}},
        {"type": "event_msg", "timestamp": start, "payload": {"type": "task_started", "turn_id": "turn"}},
        {"type": "turn_context", "payload": {"model": plan["model"], "effort": actual_effort or plan["reasoningEffort"]}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": f"WorkflowPlan: {plan_path}\nExecute this offline fixture."}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "channel": "final", "content": [{"type": "output_text", "text": report if report is not None else workflow_report(role=plan["role"])}]}},
        {"type": "event_msg", "timestamp": end, "payload": {"type": "turn_aborted" if aborted else "task_complete", "turn_id": "turn"}},
    ]
    log.write_text("".join(json.dumps(r) + "\n" for r in records))
    run("record-native-run", "-PlanFile", str(plan_path), "-AgentId", agent, "-TranscriptPath", str(log))
    lifecycle.record_agent_terminal(root, "new", plan["taskId"], agent, log)
    return log


def checks(project):
    p, root = project
    f = root / "checks-input.json"
    f.write_text(json.dumps({"checks": [{"argv": [sys.executable, "-c", "import pathlib; assert 'value = 1' in pathlib.Path('app.py').read_text()"]}]}))
    assert run("run-checks", "-WorkflowId", "new", "-ArtifactRoot", str(root), "-ChecksFile", str(f)) == 0
    return max((root / "checks").glob("*/evidence.json"), key=lambda path: path.stat().st_mtime_ns)


def main_review(project, monkeypatch, evidence):
    p, root = project
    monkeypatch.setenv("CODEX_THREAD_ID", "main")
    monkeypatch.delenv("CODEX_CLAUDE_CHILD_THREAD", raising=False)
    log = lifecycle.sessions_root() / "rollout-main.jsonl"
    log.write_text(json.dumps({"type": "session_meta", "payload": {"id": "main", "cwd": str(p), "source": "cli"}}) + "\n")
    review = root / "review.md"
    review.write_text("Scope compliance: app.py is unchanged. Quality: the value is correct. Residual risks: none in this offline fixture.")
    return run("record-main-review", "-WorkflowId", "new", "-ArtifactRoot", str(root), "-EvidenceFile", str(evidence), "-ReviewFile", str(review))


def test_native_standard_end_to_end_and_stale_code_rejected(project, monkeypatch):
    plan = prepare(project)
    native_complete(project, monkeypatch, plan)
    p, root = project
    assert load_json(workflow.workflow_path(root, "new"))["finalAcceptance"]["status"] == "pending-main-review"
    evidence = checks(project)
    assert main_review(project, monkeypatch, evidence) == 0
    assert run("verify-workflow", "-WorkflowId", "new", "-ArtifactRoot", str(root)) == 0
    (p / "app.py").write_text("value = 2\n")
    with pytest.raises(DelegateError, match="stale"):
        run("verify-workflow", "-WorkflowId", "new", "-ArtifactRoot", str(root))


def test_profile_cannot_change_after_preparation(project):
    p, root = project
    prepare(project)
    with pytest.raises(DelegateError, match="frozen"):
        run("configure-workflow", "-WorkflowId", "new", "-ProjectRoot", str(p), "-ArtifactRoot", str(root), "-Profile", "strict")


def test_carrier_and_worker_models_are_separate_and_hook_checks_plan(project):
    plan_path = prepare(project, "claude-code")
    p = load_json(plan_path)
    assert p["model"] == "gpt-5.6-luna"
    assert load_json(plan_path.parent / "launch.json")["model"] == "sonnet"
    payload = {"hook_event_name": "PreToolUse", "tool_name": "spawn_agent", "tool_input": {
        "message": f"WorkflowPlan: {plan_path}", "model": "gpt-5.6-luna", "reasoning_effort": "low", "fork_turns": "none"}}
    assert run_hook(payload) == {}
    payload["tool_input"]["model"] = "gpt-6-astra"
    assert run_hook(payload)["hookSpecificOutput"]["permissionDecision"] == "deny"
    payload["tool_input"]["model"] = "gpt-5.6-luna"
    del payload["tool_input"]["fork_turns"]
    assert run_hook(payload)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_failed_check_cannot_be_recorded_as_review(project):
    p, root = project
    f = root / "bad-check.json"
    f.write_text(json.dumps({"checks": [{"argv": [sys.executable, "-c", "raise SystemExit(3)"]}]}))
    assert run("run-checks", "-WorkflowId", "new", "-ArtifactRoot", str(root), "-ChecksFile", str(f)) == 1


def test_native_host_report_change_blocks_acceptance(project, monkeypatch):
    plan = prepare(project)
    log = native_complete(project, monkeypatch, plan)
    _, root = project
    log.write_text(log.read_text().replace('"model": "gpt-6-astra"', '"model": "gpt-5.6-luna"'))
    with pytest.raises(DelegateError, match="evidence changed"):
        run("verify-workflow", "-WorkflowId", "new", "-ArtifactRoot", str(root))


def carrier_log(project, monkeypatch, model="gpt-5.6-luna"):
    p, root = project
    thread = "00000000-0000-0000-0000-000000000099"
    monkeypatch.setenv("CODEX_THREAD_ID", thread)
    path = lifecycle.sessions_root() / f"rollout-{thread}.jsonl"
    from codex_with_cc_runtime.common import now_iso
    records = [
        {"type": "session_meta", "payload": {"id": thread, "cwd": str(p), "source": {"subagent": {"thread_spawn": {"parent_thread_id": "main", "agent_path": "/root/carrier"}}}}},
        {"type": "event_msg", "timestamp": now_iso(), "payload": {"type": "task_started", "turn_id": "carrier-turn"}},
        {"type": "turn_context", "payload": {"model": model}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "WorkflowPlan: " + list(load_json(workflow.workflow_path(root, "new"))["preparedTasks"].values())[-1]["path"]}},
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def test_prepared_launcher_binds_actual_child_and_keeps_template(project, monkeypatch):
    from codex_with_cc_runtime import fixed_launcher
    plan = prepare(project, "claude-code")
    carrier_log(project, monkeypatch)
    path = plan.parent / "launch.json"
    original = path.read_bytes()
    descriptor = fixed_launcher.read_launch_descriptor(plan.parent)
    fixed_launcher.validate_descriptor(descriptor)
    fixed_launcher.check_paths(descriptor)
    fixed_launcher.check_thread_binding(descriptor)
    assert descriptor["childThread"]["threadId"] == os.environ["CODEX_THREAD_ID"]
    assert path.read_bytes() == original
    carrier_log(project, monkeypatch, model="gpt-6-astra")
    with pytest.raises(DelegateError, match="model"):
        fixed_launcher.read_launch_descriptor(plan.parent)


@pytest.mark.skipif(os.name != "posix", reason="POSIX fixed launcher integration")
def test_prepared_claude_launcher_executes_and_standard_accepts(project, monkeypatch, tmp_path):
    from tests.test_superpowers_workflow_overhaul import make_fake_claude_bin
    from codex_with_cc_runtime.common import now_iso
    p, root = project
    plan = prepare(project, "claude-code")
    log = carrier_log(project, monkeypatch)
    workflow.record_agent_spawn(root, "new", "impl", "/root/carrier")
    fake = make_fake_claude_bin(tmp_path, "implementer", "- local fixture check passed")
    scripts = Path(__file__).resolve().parents[1] / "skills/codex-with-cc/scripts"
    env = {**os.environ, "PATH": str(fake) + os.pathsep + os.environ.get("PATH", "")}
    result = subprocess.run([sys.executable, str(scripts / "fixed_launcher.py")], cwd=plan.parent,
                            env=env, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    w = load_json(workflow.workflow_path(root, "new"))
    rid = w["tasks"]["impl"]["latestRunId"]
    assert w["preparedTasks"][load_json(plan)["planId"]]["runId"] == rid
    with log.open("a") as handle:
        handle.write(json.dumps({"type": "event_msg", "timestamp": now_iso(), "payload": {"type": "task_complete", "turn_id": "carrier-turn"}}) + "\n")
    lifecycle.record_agent_terminal(root, "new", "impl", "/root/carrier", log)
    assert main_review(project, monkeypatch, checks(project)) == 0
    assert run("verify-workflow", "-WorkflowId", "new", "-ArtifactRoot", str(root)) == 0


def test_interrupted_native_attempt_can_settle_but_needs_fresh_success(project, monkeypatch):
    _, root = project
    plan = prepare(project)
    native_complete(project, monkeypatch, plan, aborted=True)
    w = load_json(workflow.workflow_path(root, "new"))
    assert w["tasks"]["impl"]["status"] == "interrupted"
    with pytest.raises(DelegateError, match="interrupted"):
        run("verify-run", "-RunId", w["tasks"]["impl"]["latestRunId"], "-ArtifactRoot", str(root))
    assert w["finalAcceptance"]["status"] != "accepted"
    assert all(a.get("settledAt") for a in w["agentAttempts"].values())
    with pytest.raises(DelegateError, match="interrupted"):
        run("verify-workflow", "-WorkflowId", "new", "-ArtifactRoot", str(root))
    native_complete(project, monkeypatch, prepare(project))
    assert main_review(project, monkeypatch, checks(project)) == 0
    assert run("verify-workflow", "-WorkflowId", "new", "-ArtifactRoot", str(root)) == 0
    assert len(load_json(workflow.workflow_path(root, "new"))["runs"]) == 2


def test_new_unexecuted_plan_invalidates_existing_acceptance(project, monkeypatch):
    _, root = project
    native_complete(project, monkeypatch, prepare(project))
    assert main_review(project, monkeypatch, checks(project)) == 0
    prepare(project)
    assert load_json(workflow.workflow_path(root, "new"))["finalAcceptance"]["status"] == "pending-task"
    with pytest.raises(DelegateError, match="pending-task"):
        run("verify-workflow", "-WorkflowId", "new", "-ArtifactRoot", str(root))


def test_main_review_rejects_child_provenance_without_marker(project, monkeypatch):
    _, root = project
    native_complete(project, monkeypatch, prepare(project))
    evidence = checks(project)
    assert main_review(project, monkeypatch, evidence) == 0
    log = lifecycle.sessions_root() / "rollout-main.jsonl"
    content = json.loads(log.read_text())
    content["payload"]["source"] = {"subagent": {"thread_spawn": {"parent_thread_id": "parent"}}}
    log.write_text(json.dumps(content) + "\n")
    with pytest.raises(DelegateError, match="subagent"):
        run("record-main-review", "-WorkflowId", "new", "-ArtifactRoot", str(root), "-EvidenceFile", str(evidence), "-ReviewFile", str(root / "review.md"))


def test_declared_commands_require_execution_evidence(project, monkeypatch):
    from codex_with_cc_runtime.check_evidence import verify_check_file
    _, root = project
    native_complete(project, monkeypatch, prepare(project))
    evidence = checks(project)
    w = load_json(workflow.workflow_path(root, "new"))
    w["tasks"]["impl"]["verification"] = ["python3 -m missing_real_suite"]
    with pytest.raises(DelegateError, match="do not cover"):
        verify_check_file(evidence, root, w)


def test_original_child_instruction_must_match_plan(project, monkeypatch):
    from codex_with_cc_runtime import fixed_launcher
    plan = prepare(project, "claude-code")
    log = carrier_log(project, monkeypatch)
    log.write_text(log.read_text().replace("WorkflowPlan:", "UnrelatedPlan:"))
    with pytest.raises(DelegateError, match="instruction"):
        fixed_launcher.read_launch_descriptor(plan.parent)


@pytest.mark.skipif(os.name != "posix", reason="POSIX timeout process cleanup")
def test_checks_timeout_terminates_owned_process_tree(project):
    _, root = project
    f = root / "timeout-check.json"
    child_marker = root / "orphan-marker"
    child_code = f"import time, pathlib; time.sleep(2); pathlib.Path({str(child_marker)!r}).write_text('orphan')"
    parent_code = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {child_code!r}]); time.sleep(30)"
    f.write_text(json.dumps({"checks": [{"argv": [sys.executable, "-c", parent_code], "timeoutSeconds": 1}]}))
    assert run("run-checks", "-WorkflowId", "new", "-ArtifactRoot", str(root), "-ChecksFile", str(f)) == 1
    import time
    time.sleep(1.3)
    assert not child_marker.exists()
