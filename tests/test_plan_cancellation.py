"""Cancellation is audited withdrawal, never fabricated execution or closure."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_execution_profiles import project, prepare, native_complete, checks, main_review, run
from tests.task_helpers import compliant_task
from tests.test_platform_hooks import run_hook
from codex_with_cc_runtime import workflow, lifecycle, fixed_launcher
from codex_with_cc_runtime.common import DelegateError
from codex_with_cc_runtime.io_utils import load_json
from codex_with_cc_runtime.routing import verified_plan
from codex_with_cc_runtime.plan_cancellation import verify_cancellations


def set_actor(project, monkeypatch, *, child=False):
    p, _ = project
    monkeypatch.chdir(p)
    monkeypatch.setenv("CODEX_THREAD_ID", "main")
    monkeypatch.delenv("CODEX_CLAUDE_CHILD_THREAD", raising=False)
    source = {"subagent": {"thread_spawn": {"parent_thread_id": "parent"}}} if child else "cli"
    (lifecycle.sessions_root() / "rollout-main.jsonl").write_text(json.dumps({
        "type": "session_meta", "payload": {"id": "main", "cwd": str(p), "source": source}}) + "\n")


def another_plan(project, task_id="unused", backend="codex-native"):
    _, root = project
    task = root / f"{task_id}.md"
    task.write_text(compliant_task("Read app.py and report the value."))
    run("prepare-task", "-WorkflowId", "new", "-TaskId", task_id, "-ArtifactRoot", str(root),
        "-TaskFile", str(task), "-Scope", "app.py", "-Backend", backend, "-Role", "researcher")
    return Path(list(load_json(workflow.workflow_path(root, "new"))["preparedTasks"].values())[-1]["path"])


def cancel(plan, reason="The main task completed this work before dispatch."):
    return run("cancel-prepared-task", "-PlanFile", str(plan), "-Reason", reason)


def receipt(root, plan):
    w = load_json(workflow.workflow_path(root, "new"))
    entry = w["preparedTasks"][load_json(plan)["planId"]]
    return Path(entry["cancellation"]["path"])


@pytest.mark.parametrize("backend", ["codex-native", "claude-code"])
def test_cancel_preserves_plan_receipt_and_idempotence_but_empty_workflow_cannot_pass(project, monkeypatch, backend):
    plan = prepare(project, backend)
    set_actor(project, monkeypatch)
    _, root = project
    original = plan.read_bytes()
    before = workflow.workflow_path(root, "new").read_bytes()
    assert cancel(plan) == 0
    r = load_json(receipt(root, plan))
    assert Path(r["backupPath"]).read_bytes() == before
    assert r["actor"]["threadId"] == "main" and r["reason"]
    assert plan.read_bytes() == original
    after = workflow.workflow_path(root, "new").read_bytes()
    assert cancel(plan) == 0
    assert workflow.workflow_path(root, "new").read_bytes() == after
    assert len(list((root / "cancellations").glob("*.json"))) == 2
    with pytest.raises(DelegateError, match="overwritten"): cancel(plan, "Different reason")
    with pytest.raises(DelegateError, match="empty workflows"):
        run("verify-workflow", "-WorkflowId", "new", "-ArtifactRoot", str(root))
    with pytest.raises(DelegateError, match="cancelled"): verified_plan(plan)
    with pytest.raises(DelegateError, match="cancelled"): workflow.record_agent_spawn(root, "new", "impl", "/root/late")
    with pytest.raises(DelegateError, match="cancelled"):
        run("record-native-run", "-PlanFile", str(plan), "-AgentId", "/root/late", "-TranscriptPath", "missing")
    if backend == "claude-code":
        with pytest.raises(DelegateError, match="cancelled"): fixed_launcher.claim_descriptor(plan.parent)
        assert not (plan.parent / "claimed").exists()
    p = load_json(plan)
    hook = run_hook({"hook_event_name": "PreToolUse", "tool_name": "spawn_agent", "tool_input": {
        "message": f"WorkflowPlan: {plan}", "model": p["model"], "reasoning_effort": p["reasoningEffort"], "fork_turns": "none"}})
    assert hook["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_withdraw_unused_plan_unblocks_existing_verified_work_without_faking_a_run(project, monkeypatch):
    _, root = project
    native_complete(project, monkeypatch, prepare(project))
    assert main_review(project, monkeypatch, checks(project)) == 0
    original = load_json(workflow.workflow_path(root, "new"))
    plan = another_plan(project)
    set_actor(project, monkeypatch)
    assert cancel(plan) == 0
    after = load_json(workflow.workflow_path(root, "new"))
    for key in ("runs", "tasks", "agentAttempts", "mainReview"):
        assert after[key] == original[key]
    assert after["finalAcceptance"]["status"] == "accepted"
    assert run("verify-workflow", "-WorkflowId", "new", "-ArtifactRoot", str(root)) == 0
    # An outstanding separate plan still blocks acceptance.
    another_plan(project, "still-required")
    with pytest.raises(DelegateError, match="pending-task"):
        run("verify-workflow", "-WorkflowId", "new", "-ArtifactRoot", str(root))


@pytest.mark.parametrize("evidence", ["spawn", "claim", "run", "orphan-config", "host-child", "parent-spawn"])
def test_cannot_cancel_dispatched_or_started_work(project, monkeypatch, evidence):
    plan = prepare(project, "claude-code")
    set_actor(project, monkeypatch)
    p, root = project
    wpath = workflow.workflow_path(root, "new")
    data = load_json(plan)
    name = "impl_" + data["planId"][:8]
    if evidence == "spawn": workflow.record_agent_spawn(root, "new", "impl", "/root/already-spawned")
    elif evidence == "claim": fixed_launcher.claim_descriptor(plan.parent)
    elif evidence == "run":
        w = load_json(wpath); w["runs"]["real-run"] = {"taskId": "impl"}; wpath.write_text(json.dumps(w))
    elif evidence == "orphan-config": (root / "config_orphan.json").write_text(json.dumps({"preparedPlanId": data["planId"]}))
    elif evidence == "host-child":
        (lifecycle.sessions_root() / "rollout-unregistered.jsonl").write_text(json.dumps({"type": "session_meta", "payload": {
            "id": "unregistered", "cwd": str(p), "source": {"subagent": {"thread_spawn": {"parent_thread_id": "main", "agent_path": "/root/" + name}}}}}) + "\n")
    elif evidence == "parent-spawn":
        w = load_json(wpath); w["mainUsageBaseline"] = {"threadId": "main"}; wpath.write_text(json.dumps(w))
        with (lifecycle.sessions_root() / "rollout-main.jsonl").open("a") as f:
            f.write(json.dumps({"type": "response_item", "payload": {"type": "function_call", "name": "spawn_agent", "namespace": "collaboration", "arguments": json.dumps({"task_name": name, "message": "opaque"})}}) + "\n")
    before = wpath.read_bytes()
    with pytest.raises(DelegateError, match="Cannot cancel"): cancel(plan)
    assert wpath.read_bytes() == before and not (root / "cancellations").exists()


@pytest.mark.parametrize("mutation", ["receipt", "missing-receipt", "backup", "missing-ref", "status-only", "plan", "actor"])
def test_cancellation_audit_is_reverified(project, monkeypatch, mutation):
    plan = prepare(project)
    set_actor(project, monkeypatch)
    _, root = project
    cancel(plan)
    rpath = receipt(root, plan); r = load_json(rpath)
    wpath = workflow.workflow_path(root, "new")
    w = load_json(wpath)
    entry = w["preparedTasks"][load_json(plan)["planId"]]
    if mutation == "receipt": rpath.write_text(rpath.read_text().replace(r["reason"], "tampered"))
    elif mutation == "missing-receipt": rpath.unlink()
    elif mutation == "backup": Path(r["backupPath"]).write_text("{}")
    elif mutation in ("missing-ref", "status-only"): entry.pop("cancellation")
    elif mutation == "plan": plan.write_text(plan.read_text() + " ")
    elif mutation == "actor": set_actor(project, monkeypatch, child=True)
    wpath.write_text(json.dumps(w))
    with pytest.raises(DelegateError):
        run("verify-workflow", "-WorkflowId", "new", "-ArtifactRoot", str(root))


def test_fresh_plan_can_reuse_cancelled_task_id_without_reviving_old_plan(project, monkeypatch):
    plan = prepare(project)
    set_actor(project, monkeypatch)
    cancel(plan)
    fresh = prepare(project)
    native_complete(project, monkeypatch, fresh)
    _, root = project
    verify_cancellations(root, load_json(workflow.workflow_path(root, "new")))
    with pytest.raises(DelegateError, match="cancelled"): verified_plan(plan)


@pytest.mark.parametrize("invalid", ["empty-reason", "child-actor", "no-actor"])
def test_cancel_requires_reason_and_real_main_actor(project, monkeypatch, invalid):
    plan = prepare(project)
    set_actor(project, monkeypatch, child=invalid == "child-actor")
    if invalid == "no-actor": monkeypatch.delenv("CODEX_THREAD_ID")
    _, root = project
    before = workflow.workflow_path(root, "new").read_bytes()
    with pytest.raises(DelegateError): cancel(plan, " " if invalid == "empty-reason" else "no longer needed")
    assert workflow.workflow_path(root, "new").read_bytes() == before


def test_closure_notice_distinguishes_ended_pending_and_never_started(project, monkeypatch):
    _, root = project
    wpath = workflow.workflow_path(root, "new")
    assert "尚未派发" in lifecycle.lifecycle_notice(load_json(wpath))
    plan = prepare(project)
    workflow.record_agent_spawn(root, "new", "impl", "/root/pending")
    assert "尚未全部核验" in lifecycle.lifecycle_notice(load_json(wpath))
    w = load_json(wpath); w["agentAttempts"].clear(); wpath.write_text(json.dumps(w))
    native_complete(project, monkeypatch, plan)
    w = load_json(wpath)
    assert lifecycle.lifecycle_notice(w) == "执行已结束；宿主不提供线程关闭接口。"
    assert all(a["closeStatus"] == "unsupported" for a in w["agentAttempts"].values())
