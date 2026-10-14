"""Offline fast-path regressions; no model or provider calls."""
import json
from pathlib import Path

import pytest

from tests.test_execution_profiles import project, run, checks, main_review
from tests.test_adaptive_cc import adaptive, prepare
from tests.test_host_log_compat import desktop_fixture, write_log
from codex_with_cc_runtime import workflow, lifecycle
from codex_with_cc_runtime.common import DelegateError
from codex_with_cc_runtime.io_utils import load_json
from codex_with_cc_runtime.routing import verified_plan
from codex_with_cc_runtime.host_evidence import verify_plan_prompt


def test_prepare_admit_emits_one_payload_and_reserves_capacity(project, monkeypatch, capsys):
    adaptive(project, monkeypatch, 1)
    capsys.readouterr()
    plan = prepare(project, "fast", "implementer", "app.py", "-Admit")
    result = json.loads(capsys.readouterr().out)
    assert result["planFile"] == str(plan) and result["spawn"]["fork_turns"] == "none"
    original = plan.read_bytes()
    p, w = verified_plan(plan)
    assert w["preparedTasks"][p["planId"]]["admission"]
    with pytest.raises(DelegateError, match="concurrency"):
        prepare(project, "blocked", "implementer", "other.py", "-Admit")
    w = load_json(workflow.workflow_path(project[1], "new"))
    entry = list(w["preparedTasks"].values())[-1]
    assert not entry.get("admission") and Path(entry["path"]).is_file()
    assert plan.read_bytes() == original


def test_prepare_admit_requires_adaptive_policy(project):
    with pytest.raises(DelegateError, match="MaxParallel"):
        prepare(project, "fast", "implementer", "app.py", "-Admit")
    assert not load_json(workflow.workflow_path(project[1], "new")).get("preparedTasks")


@pytest.mark.parametrize("producer", ["prepare-task -Admit", "prepare-task"])
def test_encrypted_admit_producer_keeps_binding(project, monkeypatch, producer):
    plan, pp, cp, parent, child, agent, report = desktop_fixture(project, adaptive=True, monkeypatch=monkeypatch)
    parent[1]["payload"]["input"] = parent[1]["payload"]["input"].replace("admit-task", producer)
    write_log(pp, parent)
    if producer == "prepare-task":
        with pytest.raises(DelegateError): verify_plan_prompt(cp, plan)
    else:
        assert verify_plan_prompt(cp, plan)["source"] == "original-parent-encrypted-dispatch"
        parent[3]["payload"]["arguments"] = parent[3]["payload"]["arguments"].replace("opaque-test", "mismatch")
        write_log(pp, parent)
        with pytest.raises(DelegateError): verify_plan_prompt(cp, plan)


def test_native_settle_and_review_packet_do_not_accept_work(project, monkeypatch, capsys):
    plan, pp, cp, parent, child, agent, report = desktop_fixture(project)
    root = project[1]
    workflow.record_agent_spawn(root, "new", "impl", agent)
    capsys.readouterr()
    assert run("record-native-run", "-PlanFile", str(plan), "-AgentId", agent, "-TranscriptPath", str(cp), "-Settle") == 0
    result = json.loads(capsys.readouterr().out)
    assert result["lifecycle"] == "settled" and result["packet"]["reportStatus"] == "DONE"
    assert Path(result["report"]).read_text() == report
    w = load_json(workflow.workflow_path(root, "new"))
    assert w["agentAttempts"][agent]["closeStatus"] == "unsupported"
    assert w["finalAcceptance"]["status"] == "pending-main-review"
    before = workflow.workflow_path(root, "new").read_bytes()
    run("review-packet", "-WorkflowId", "new", "-ArtifactRoot", str(root))
    packet = json.loads(capsys.readouterr().out)
    assert packet["advisoryOnly"] is True and packet["runs"][0]["runId"] == result["runId"]
    assert workflow.workflow_path(root, "new").read_bytes() == before
    assert main_review(project, monkeypatch, checks(project)) == 0
    assert run("verify-workflow", "-WorkflowId", "new", "-ArtifactRoot", str(root)) == 0


def test_settle_rejects_strict_close_before_import(project):
    plan, pp, cp, parent, child, agent, report = desktop_fixture(project)
    root = project[1]
    workflow.record_agent_spawn(root, "new", "impl", agent)
    wp = workflow.workflow_path(root, "new")
    w = load_json(wp); w["lifecyclePolicy"] = {"policy": "strict-close"}; wp.write_text(json.dumps(w))
    with pytest.raises(DelegateError, match="terminal-evidence"):
        run("record-native-run", "-PlanFile", str(plan), "-AgentId", agent, "-TranscriptPath", str(cp), "-Settle")
    assert not load_json(wp)["runs"]


@pytest.mark.parametrize("args,expected", [((), "single-worker"), (("-Independent",), "delegate"),
    (("-Independent", "-Coupled"), "single-worker"), (("-WorkKind", "decision"), "main"),
    (("-WorkKind", "discussion"), "main"), (("-SmallKnownTask",), "main"),
    (("-Independent", "-EstimatedMinutes", "1"), "single-worker")])
def test_routing_keeps_development_in_workers(args, expected, capsys):
    run("advise-task", *args)
    assert json.loads(capsys.readouterr().out)["suggestion"] == expected


@pytest.mark.parametrize("mutation", ["model", "report", "ciphertext", "terminal"])
def test_settle_rejects_invalid_original_evidence(project, mutation):
    plan, pp, cp, parent, child, agent, report = desktop_fixture(project)
    if mutation == "model": child[3]["payload"]["model"] = "wrong-model"
    elif mutation == "report": child[5]["payload"]["content"][0]["text"] = report.replace("## Findings", "## Unknown")
    elif mutation == "ciphertext": child[4]["payload"]["content"][1]["encrypted_content"] = "wrong"
    elif mutation == "terminal": child.pop()
    write_log(cp, child)
    root = project[1]
    workflow.record_agent_spawn(root, "new", "impl", agent)
    with pytest.raises(DelegateError):
        run("record-native-run", "-PlanFile", str(plan), "-AgentId", agent, "-TranscriptPath", str(cp), "-Settle")
    assert not load_json(workflow.workflow_path(root, "new"))["runs"]


def test_packet_bounds_findings_preserves_failure_and_stale_acceptance(project, monkeypatch, capsys):
    from codex_with_cc_runtime.packets import review_packet
    plan, pp, cp, parent, child, agent, report = desktop_fixture(project)
    long_findings = "\n".join(f"- Finding {i}: inspect original evidence for this boundary condition." for i in range(500))
    report = report.replace("\nDONE\n", "\nFAIL\n").replace("## Findings\n", "## Findings\n" + long_findings + "\n")
    child[5]["payload"]["content"][0]["text"] = report
    write_log(cp, child)
    root = project[1]
    workflow.record_agent_spawn(root, "new", "impl", agent)
    run("record-native-run", "-PlanFile", str(plan), "-AgentId", agent, "-TranscriptPath", str(cp), "-Settle")
    first = review_packet(root, "new")
    assert first == review_packet(root, "new")
    row = first["runs"][0]
    assert row["reportStatus"] == "FAIL" and row["findings"]["truncated"]
    assert row["findings"]["originalChars"] > 30000 and len(row["findings"]["text"]) == 480
    assert Path(row["artifacts"]["report"]).read_text() == report
    with pytest.raises(DelegateError): main_review(project, monkeypatch, checks(project))
    # The packet always marks cached decisions as unverified observations.
    wp = workflow.workflow_path(root, "new")
    state = load_json(wp); state["finalAcceptance"] = {"status": "accepted"}; wp.write_text(json.dumps(state))
    stale = review_packet(root, "new")
    assert stale["recordedAcceptance"] == "accepted" and stale["acceptanceFreshness"].startswith("not-verified")
    assert stale["advisoryOnly"]
    state["tasks"]["alias"] = dict(state["tasks"]["impl"]); wp.write_text(json.dumps(state))
    assert review_packet(root, "new", limit=1)["omittedRuns"] == 1


@pytest.mark.parametrize("failed", [False, True])
def test_prepared_carrier_delivers_packet_and_keeps_diagnostics(project, monkeypatch, tmp_path, failed):
    import os
    import subprocess
    import sys
    from tests.test_execution_profiles import carrier_log
    from tests.test_superpowers_workflow_overhaul import make_fake_claude_bin
    plan = prepare(project, "impl", "implementer", "app.py", "-Backend", "claude-code")
    carrier_log(project, monkeypatch)
    workflow.record_agent_spawn(project[1], "new", "impl", "/root/carrier")
    fake = make_fake_claude_bin(tmp_path, "implementer", "- offline fixture passed")
    if failed:
        binary = fake / "claude"
        binary.write_text(binary.read_text().replace('"DONE', '"FAIL').replace('\\nDONE', '\\nFAIL'))
    scripts = Path(__file__).resolve().parents[1] / "skills/codex-with-cc/scripts"
    result = subprocess.run([sys.executable, str(scripts / "fixed_launcher.py")], cwd=plan.parent,
        env={**os.environ, "PATH": str(fake) + os.pathsep + os.environ.get("PATH", "")},
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    packet = json.loads(result.stdout)
    assert packet["exitCode"] == 0
    assert packet["packet"]["reportStatus"] == ("FAIL" if failed else "DONE")
    assert "Delegating to Claude Code" in Path(packet["logPath"]).read_text()
    assert "Delegating to Claude Code" not in result.stdout
    assert Path(packet["packet"]["artifacts"]["report"]).is_file()
    assert packet["packet"]["lifecycle"][0]["settled"] is False


@pytest.mark.parametrize("failure", ["execution", "packet"])
def test_carrier_exception_exposes_log_without_masking_execution(project, monkeypatch, failure, capsys):
    from codex_with_cc_runtime import fixed_launcher, packets
    from tests.test_execution_profiles import carrier_log
    plan = prepare(project, "impl", "implementer", "app.py", "-Backend", "claude-code")
    carrier_log(project, monkeypatch)
    monkeypatch.chdir(plan.parent)
    if failure == "execution":
        def broken(*args):
            print("original diagnostic")
            raise OSError("execution failed")
        monkeypatch.setattr(fixed_launcher, "run_delegate", broken)
    else:
        def completed(*args):
            wp = workflow.workflow_path(project[1], "new")
            state = load_json(wp)
            state["preparedTasks"][load_json(plan)["planId"]]["runId"] = "failed-run"
            wp.write_text(json.dumps(state))
            return 7
        def broken_packet(*args):
            raise OSError("packet failed")
        monkeypatch.setattr(fixed_launcher, "run_delegate", completed)
        monkeypatch.setattr(packets, "run_packet", broken_packet)
    capsys.readouterr()
    assert fixed_launcher.main([]) == (1 if failure == "execution" else 7)
    result = json.loads(capsys.readouterr().out)
    assert result["exitCode"] == (1 if failure == "execution" else 7)
    assert "Traceback" in Path(result["logPath"]).read_text()
    assert result.get("executionError", result.get("packetError")) == failure + " failed"
