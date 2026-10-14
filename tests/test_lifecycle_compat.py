"""Offline fixtures only: no model calls and no fabricated production evidence."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/codex-with-cc/scripts"
sys.path.insert(0, str(SCRIPTS))

from codex_with_cc_runtime import artifacts, lifecycle, workflow as wf
from codex_with_cc_runtime.cli import build_parser
from codex_with_cc_runtime.common import ARTIFACT_SCHEMA_VERSION, CHILD_MARKER_NAME, INVOCATION_CONTRACT, DelegateError
from codex_with_cc_runtime.io_utils import load_json, write_json
from tests.test_hardening_v1_1 import REPORT

THREAD = "01a06c39-515c-7c80-a3ab-d14fdcfaa3b2"
HANDLE = "/root/test_lifecycle"


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def execution(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    session_root = lifecycle.sessions_root()
    session_root.mkdir(parents=True)
    root = tmp_path / "artifacts"
    root.mkdir()
    caps = tmp_path / "tools.json"
    save(caps, {"schemaVersion": 1, "source": "active-tool-catalog", "tools": [
        "collaboration.spawn_agent", "collaboration.wait_agent", "collaboration.list_agents",
        "collaboration.interrupt_agent"]})
    report = root / "report.md"
    report.write_text(REPORT, encoding="utf-8")
    wf.record_agent_spawn(root, "wf", "task", HANDLE)
    wf.update_workflow_record(root, "wf", "task", "researcher", [], [], [], "run",
        root / "config_run.json", root / "status_run.json", report, root / "prompt",
        root / "stream", root / "trace", "completed", codex_thread_id=THREAD)
    common = {"artifactSchema": ARTIFACT_SCHEMA_VERSION, "invocationContract": INVOCATION_CONTRACT,
        "childThreadMarkerName": CHILD_MARKER_NAME, "childThreadMarkerValidated": True,
        "workflowId": "wf", "taskId": "task", "runId": "run", "role": "researcher",
        "codexThreadId": THREAD, "outputPath": str(report), "exitCode": 0,
        "attemptCount": 1, "retryCount": 0}
    save(root / "config_run.json", {**common, "repoRoot": str(tmp_path), "sessionMode": "PrimaryReuse",
        "sessionKey": "wf", "initialSessionId": "session", "initialResume": False,
        "sessionStatePath": str(root / "session.json")})
    save(root / "status_run.json", {**common, "status": "completed", "pid": 123456789,
        "updatedAt": "2026-09-04T10:01:00Z", "attempts": [{"attempt": 1,
        "sessionId": "session", "resume": False, "retryReason": None, "exitCode": 0,
        "sawAssistantText": True, "sawResultSuccess": True, "capturedFinalResult": True}]})
    save(root / "session.json", {"primary": {"leaseRunId": None}})
    log = session_root / f"rollout-2026-09-04T10-00-00-{THREAD}.jsonl"
    records = [
        {"type": "session_meta", "payload": {"id": THREAD, "cwd": str(tmp_path),
         "source": {"subagent": {"thread_spawn": {"parent_thread_id": "parent", "agent_path": HANDLE}}}}},
        {"type": "event_msg", "timestamp": "2026-09-04T10:00:00Z",
         "payload": {"type": "task_started", "turn_id": "turn"}},
        {"type": "event_msg", "timestamp": "2026-09-04T10:02:00Z",
         "payload": {"type": "task_complete", "turn_id": "turn"}},
    ]
    log.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    def dead_pid(pid, sig):
        raise ProcessLookupError(pid)
    monkeypatch.setattr(lifecycle.os, "kill", dead_pid)
    return root, caps, log


def migrate(execution):
    root, caps, _ = execution
    return lifecycle.configure_lifecycle(root, "wf", "terminal-evidence", caps, True)


def test_preflight_fails_before_workflow_creation(execution):
    root, caps, _ = execution
    with pytest.raises(DelegateError, match="lacks close_agent"):
        lifecycle.configure_lifecycle(root, "new", "strict-close", caps)
    assert not wf.workflow_path(root, "new").exists()


def test_real_execution_requires_preflight(execution):
    root, _, _ = execution
    with pytest.raises(DelegateError, match="preflight"):
        lifecycle.require_lifecycle_preflight(root, "new")
    with pytest.raises(DelegateError, match="policy"):
        lifecycle.require_lifecycle_preflight(root, "wf")
    migrate(execution)
    lifecycle.require_lifecycle_preflight(root, "wf")


def test_tampered_aggregate_cannot_accept_a_changed_report(execution):
    root, _, _ = execution
    path = wf.workflow_path(root, "wf")
    wf.record_agent_close(root, "wf", "task", HANDLE)
    assert load_json(path)["finalAcceptance"]["status"] == "accepted"
    (root / "report.md").write_text(REPORT.replace("DONE", "BLOCKED"))
    with pytest.raises(DelegateError, match="report/aggregate mismatch"):
        artifacts.run_verify_workflow(argparse.Namespace(workflow_id="wf", artifact_root=str(root)))


@pytest.mark.parametrize("tools", [[], ["spawn_agent"], ["wait"], ["spawn_agent", "wait", "close_agent"]])
def test_invalid_or_close_capable_host_cannot_use_terminal_policy(execution, tools):
    _, caps, _ = execution
    doc = load_json(caps)
    doc["tools"] = tools
    with pytest.raises(DelegateError):
        lifecycle.capability_profile(doc, "terminal-evidence")


def test_strict_host_profile(execution):
    _, caps, _ = execution
    doc = load_json(caps)
    doc["tools"].append("close_agent")
    assert lifecycle.capability_profile(doc, "strict-close")["closeSupported"] is True


def test_terminal_adapter_rejects_non_posix_without_pid_probe(execution, monkeypatch):
    _, caps, _ = execution
    document = load_json(caps)
    monkeypatch.setattr(lifecycle.os, "name", "nt")
    with pytest.raises(DelegateError, match="POSIX"):
        lifecycle.capability_profile(document, "terminal-evidence")


def test_terminal_policy_requires_child_attempt_for_every_run(execution):
    path = migrate(execution)
    data = load_json(path)
    data["agentAttempts"] = {}
    wf.update_workflow_acceptance(data)
    assert data["finalAcceptance"]["status"] == "pending-agent-terminal"


def test_migration_requires_opt_in_and_preserves_exact_backup(execution):
    root, caps, _ = execution
    path = wf.workflow_path(root, "wf")
    before = path.read_bytes()
    with pytest.raises(DelegateError, match="MigrateExisting"):
        lifecycle.configure_lifecycle(root, "wf", "terminal-evidence", caps)
    assert path.read_bytes() == before
    migrate(execution)
    data = load_json(path)
    assert Path(data["lifecyclePolicyHistory"][0]["backupPath"]).read_bytes() == before
    assert data["finalAcceptance"]["status"] == "pending-agent-terminal"
    assert (root / "report.md").read_text() == REPORT


def test_terminal_is_not_close_and_is_idempotent(execution):
    root, _, log = execution
    path = migrate(execution)
    with pytest.raises(DelegateError, match="does not support"):
        wf.record_agent_close(root, "wf", "task", HANDLE)
    lifecycle.record_agent_terminal(root, "wf", "task", HANDLE, log)
    before = path.read_bytes()
    lifecycle.record_agent_terminal(root, "wf", "task", THREAD, log)
    assert path.read_bytes() == before
    data = load_json(path)
    assert data["agentAttempts"][HANDLE]["closeStatus"] == "unsupported"
    assert data["agentAttempts"][HANDLE]["executionStatus"] == "completed"
    assert data["finalAcceptance"]["status"] == "accepted"
    assert artifacts.run_verify_workflow(argparse.Namespace(workflow_id="wf", artifact_root=str(root))) == 0
    with pytest.raises(DelegateError, match="settled"):
        wf.record_agent_spawn(root, "wf", "task", HANDLE)


@pytest.mark.parametrize("mutation", ["wrong-id", "wrong-cwd", "wrong-handle", "wrong-parent", "wrong-turn",
    "running", "interrupted", "no-provenance", "truncated", "malformed", "tampered-after-settle"])
def test_host_evidence_fails_closed(execution, mutation):
    root, _, log = execution
    path = migrate(execution)
    if mutation == "tampered-after-settle":
        lifecycle.record_agent_terminal(root, "wf", "task", HANDLE, log)
        log.write_text(log.read_text() + json.dumps({"type": "event_msg", "payload": {"type": "token_count"}}) + "\n")
        with pytest.raises(DelegateError, match="changed"):
            lifecycle.verify_lifecycle_evidence(root, load_json(path))
        return
    records = [json.loads(line) for line in log.read_text().splitlines()]
    meta = records[0]["payload"]
    if mutation == "wrong-id": meta["id"] = "different"
    if mutation == "wrong-cwd": meta["cwd"] = str(root)
    if mutation == "wrong-handle": meta["source"]["subagent"]["thread_spawn"]["agent_path"] = "/root/other"
    if mutation == "wrong-parent": meta["parent_thread_id"] = "different"
    if mutation == "wrong-turn": records[-1]["payload"]["turn_id"] = "different"
    if mutation == "no-provenance": meta["source"] = {"subagent": "malformed"}
    if mutation == "interrupted": records[-1]["payload"]["type"] = "turn_aborted"
    if mutation == "running": records.append(records[1])
    content = "".join(json.dumps(r) + "\n" for r in records)
    if mutation == "truncated": content = content.rstrip()
    if mutation == "malformed": content += "{invalid}\n"
    log.write_text(content)
    with pytest.raises(DelegateError):
        lifecycle.record_agent_terminal(root, "wf", "task", HANDLE, log)
    assert "executionEvidence" not in load_json(path)["agentAttempts"][HANDLE]


@pytest.mark.parametrize("mutation", ["live-pid", "missing-exit", "recovered", "dry-run", "fallback",
    "wrong-run", "wrong-time", "held-lease", "running", "different-report"])
def test_runner_evidence_fails_closed(execution, monkeypatch, mutation):
    root, _, log = execution
    path = migrate(execution)
    status = load_json(root / "status_run.json")
    config = load_json(root / "config_run.json")
    if mutation == "live-pid": monkeypatch.setattr(lifecycle.os, "kill", lambda *_: None)
    if mutation == "missing-exit": status.pop("exitCode")
    if mutation == "recovered": status["statusRecoveredFromReport"] = True
    if mutation == "dry-run": config["dryRun"] = True
    if mutation == "fallback": config["trustedLocalFallback"] = True
    if mutation == "wrong-run": status["runId"] = "other"
    if mutation == "wrong-time": status["updatedAt"] = "2026-09-04T09:00:00Z"
    if mutation == "held-lease": save(root / "session.json", {"primary": {"leaseRunId": "run"}})
    if mutation == "running": status["status"] = "running"
    if mutation == "different-report": (root / "report.md").write_text("not a report")
    save(root / "config_run.json", config)
    save(root / "status_run.json", status)
    before = (root / "status_run.json").read_bytes()
    with pytest.raises(DelegateError):
        lifecycle.record_agent_terminal(root, "wf", "task", HANDLE, log)
    assert (root / "status_run.json").read_bytes() == before
    assert "executionEvidence" not in load_json(path)["agentAttempts"][HANDLE]


def test_log_must_be_original_bounded_and_not_symlink(execution, tmp_path, monkeypatch):
    root, _, log = execution
    migrate(execution)
    copy = tmp_path / "copied.jsonl"
    copy.write_bytes(log.read_bytes())
    with pytest.raises(DelegateError, match="original Codex"):
        lifecycle.record_agent_terminal(root, "wf", "task", HANDLE, copy)
    link = log.with_name("link.jsonl")
    link.symlink_to(log)
    with pytest.raises(DelegateError, match="symlink"):
        lifecycle.record_agent_terminal(root, "wf", "task", HANDLE, link)
    monkeypatch.setattr(lifecycle, "MAX_LINE_BYTES", 20)
    with pytest.raises(DelegateError, match="oversized"):
        lifecycle.record_agent_terminal(root, "wf", "task", HANDLE, log)


def test_audit_is_read_only_and_does_not_accept_old_blocked_report(execution):
    root, _, log = execution
    report = root / "report.md"
    report.write_text(REPORT.replace("DONE", "BLOCKED"))
    before = {p: p.read_bytes() for p in root.iterdir() if p.is_file()}
    result = lifecycle.audit_lifecycle(root, "wf")
    assert result["attempts"][0]["eligible"] is True
    assert all(p.read_bytes() == content for p, content in before.items())
    # Update aggregate from the genuine BLOCKED report, not from evidence settlement.
    wf.update_workflow_record(root, "wf", "task", "researcher", [], [], [], "run",
        root / "config_run.json", root / "status_run.json", report, root / "prompt",
        root / "stream", root / "trace", "completed", codex_thread_id=THREAD)
    path = migrate(execution)
    lifecycle.record_agent_terminal(root, "wf", "task", HANDLE, log)
    assert load_json(path)["finalAcceptance"]["status"] == "needs-review"
    assert "BLOCKED" in report.read_text()


def test_legacy_close_gate_unchanged(execution):
    root, _, _ = execution
    path = wf.workflow_path(root, "wf")
    assert load_json(path)["finalAcceptance"]["status"] == "pending-agent-close"


def test_final_inputs_do_not_depend_on_their_own_final_report(tmp_path):
    from tests.test_superpowers_workflow_overhaul import run_delegate, run_id_from_output
    root = tmp_path / "artifacts"
    impl = run_delegate(tmp_path, root, "implement", "implementer")
    assert impl.returncode == 0, impl.stdout + impl.stderr
    impl_id = run_id_from_output(impl.stdout)
    for kind in ("spec", "quality"):
        review = run_delegate(tmp_path, root, kind, "reviewer", "-ReviewForTaskId", "implement",
            "-ReviewForRunId", impl_id, "-ReviewKind", kind)
        assert review.returncode == 0, review.stdout + review.stderr
    ns = argparse.Namespace(workflow_id="wf-review-gate", artifact_root=str(root))
    assert artifacts.run_verify_final_inputs(ns) == 0
    with pytest.raises(DelegateError, match="final-verifier"):
        artifacts.run_verify_workflow(ns)
    path = wf.workflow_path(root, ns.workflow_id)
    data = load_json(path)
    data["tasks"]["implement"]["reviews"]["spec"]["reviewedRunId"] = "stale"
    write_json(path, data)
    with pytest.raises(DelegateError, match="stale"):
        artifacts.run_verify_final_inputs(ns)


def test_cli_lifecycle_commands():
    parser = build_parser()
    assert parser.parse_args(["audit-lifecycle", "-WorkflowId", "wf"]).command == "audit-lifecycle"
    ns = parser.parse_args(["configure-lifecycle", "-WorkflowId", "wf", "-Policy", "terminal-evidence",
        "-HostToolsFile", "tools.json", "-MigrateExisting"])
    assert ns.migrate_existing is True
