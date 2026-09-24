"""Behavioral regression for retry diagnosis, ordered writes and check races."""

import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from tests.test_adaptive_native import managed, register, finish, transcript
from codex_native_agents_runtime import evidence, planning, workflow as w
from codex_native_agents_runtime.cli import main


CLI = Path(__file__).resolve().parents[1] / "skills/codex-native-agents/scripts/native_agents.py"
DIAGNOSIS = {"escalation_cause": "quality", "escalation_note": "Observed incorrect boundary classification in the original report."}


def fail_attempt(managed, status):
    flow = managed[0]
    register(managed)
    payload = planning.prepare_spawn(flow, "work")
    w.record_spawn(flow, task_id="work", agent_id="first", actual_model=payload["model"])
    path, report = transcript(managed, "work", "first", status=status)
    w.record_run(flow, task_id="work", agent_id="first", report=report, transcript_path=path)
    w.record_close(flow, task_id="work", agent_id="first", status="unsupported", transcript_path=path)


@pytest.mark.parametrize("status", ["NEEDS_CONTEXT", "BLOCKED"])
def test_context_and_blocked_reports_cannot_escalate_or_consume_slots(managed, status):
    flow = managed[0]
    fail_attempt(managed, status)
    flow["policy"]["host"]["maxAgents"] = 1
    register(managed, "independent", scopes=("other.py",), parallel=True)
    before = copy.deepcopy(flow)
    wave = planning.ready_tasks(flow)
    assert wave["ready"] == ["independent"]
    assert wave["requiresEscalation"] == []
    assert status in wave["blocked"]["work"][0]
    with pytest.raises(ValueError, match=status):
        planning.prepare_spawn(flow, "work", escalate=True, **DIAGNOSIS)
    assert flow == before
    with pytest.raises(ValueError):
        w.verify_workflow(flow)


@pytest.mark.parametrize("status", ["FAIL", "DONE_WITH_CONCERNS"])
def test_valid_quality_retry_requires_and_preserves_diagnosis(managed, status):
    flow = managed[0]
    fail_attempt(managed, status)
    before = copy.deepcopy(flow)
    for diagnosis in [{}, {**DIAGNOSIS, "escalation_note": " "}, {**DIAGNOSIS, "escalation_cause": "environment"}]:
        with pytest.raises(ValueError, match="Escalation requires"):
            planning.prepare_spawn(flow, "work", escalate=True, **diagnosis)
        assert flow == before
    payload = planning.prepare_spawn(flow, "work", escalate=True, **DIAGNOSIS)
    assert payload["model"] == "gpt-6-astra"
    spawn = w.record_spawn(flow, task_id="work", agent_id="second", actual_model=payload["model"])
    note = spawn["prepared"]["escalationDiagnosis"]
    assert note["previousStatus"] == status and note["previousAgentId"] == "first"
    assert note["previousRunId"] == flow["tasks"]["work"]["lastRunId"]
    assert note["cause"] == "quality" and note["note"] == DIAGNOSIS["escalation_note"]


def test_unrecorded_completed_report_cannot_bypass_retry_status(managed):
    flow = managed[0]
    register(managed)
    payload = planning.prepare_spawn(flow, "work")
    w.record_spawn(flow, task_id="work", agent_id="first", actual_model=payload["model"])
    path, _ = transcript(managed, "work", "first", status="NEEDS_CONTEXT")
    w.record_close(flow, task_id="work", agent_id="first", status="unsupported", transcript_path=path)
    assert planning.ready_tasks(flow)["requiresEscalation"] == []
    with pytest.raises(ValueError, match="Missing verified failure"):
        planning.prepare_spawn(flow, "work", escalate=True, **DIAGNOSIS)


def test_cli_diagnosis_is_bound_to_retry(managed, capsys):
    flow, _, root, _ = managed
    fail_attempt(managed, "FAIL")
    w.write_workflow(root, flow)
    args = ["--artifact-root", str(root), "prepare-spawn", "--workflow-id", "adaptive", "--task-id", "work", "--escalate"]
    with pytest.raises(SystemExit):
        main(args)
    assert w.load_workflow(root, "adaptive") == flow
    assert main(args + ["--escalation-cause", "quality", "--escalation-note", "Original test report failed at a boundary."]) == 0
    assert json.loads(capsys.readouterr().out)["model"] == "gpt-6-astra"


@pytest.mark.parametrize("transitive", [False, True])
def test_ordered_writers_can_overlap_unrelated_work_but_never_each_other(managed, transitive):
    flow = managed[0]
    register(managed, "a", parallel=True)
    dependency = "a"
    if transitive:
        register(managed, "middle", role="researcher", scopes=("docs",), writable=False, parallel=True, depends_on=["a"])
        dependency = "middle"
    register(managed, "b", parallel=True, depends_on=[dependency])
    register(managed, "unrelated", scopes=("other.py",), parallel=True)
    assert planning.ready_tasks(flow)["ready"] == ["a", "unrelated"]
    planning.prepare_spawn(flow, "unrelated")
    with pytest.raises(ValueError, match="dependency"):
        planning.prepare_spawn(flow, "b")
    finish(managed, "a", "a-agent")
    if transitive:
        with pytest.raises(ValueError, match="dependency"):
            planning.prepare_spawn(flow, "b")
        finish(managed, "middle", "middle-agent")
    assert planning.ready_tasks(flow)["ready"] == ["b"]
    planning.prepare_spawn(flow, "b")
    assert flow["tasks"]["unrelated"]["prepared"]
    register(managed, "reader", role="researcher", writable=False, parallel=True)
    with pytest.raises(ValueError, match="active scope"):
        planning.prepare_spawn(flow, "reader")


@pytest.mark.parametrize("status", ["FAIL", "BLOCKED", "DONE_WITH_CONCERNS", "DONE"])
def test_dependent_write_waits_for_successful_report_and_settlement(managed, status):
    flow = managed[0]
    register(managed, "a", parallel=True)
    register(managed, "b", parallel=True, depends_on=["a"])
    payload = planning.prepare_spawn(flow, "a")
    w.record_spawn(flow, task_id="a", agent_id="a-agent", actual_model=payload["model"])
    path, report = transcript(managed, "a", "a-agent", status=status)
    w.record_run(flow, task_id="a", agent_id="a-agent", report=report, transcript_path=path)
    with pytest.raises(ValueError, match="dependency"):
        planning.prepare_spawn(flow, "b")
    w.record_close(flow, task_id="a", agent_id="a-agent", status="unsupported", transcript_path=path)
    if status == "DONE":
        planning.prepare_spawn(flow, "b")
    else:
        with pytest.raises(ValueError, match="dependency"):
            planning.prepare_spawn(flow, "b")


def test_common_ancestor_is_not_an_order_between_writers(managed):
    register(managed, "parent", scopes=("base.py",), parallel=True)
    register(managed, "left", parallel=True, depends_on=["parent"])
    before = copy.deepcopy(managed[0])
    with pytest.raises(ValueError, match="overlap"):
        register(managed, "right", parallel=True, depends_on=["parent"])
    assert managed[0] == before


def setup_checks(managed):
    flow, _, root, _ = managed
    register(managed)
    finish(managed)
    w.write_workflow(root, flow)
    return [sys.executable, str(CLI), "--artifact-root", str(root)]


def check_file(root, name, code="pass"):
    path = root / (name + ".json")
    path.write_text(json.dumps({"checks": [{"argv": [sys.executable, "-c", code], "timeoutSeconds": 15}]}))
    return path


def run_cli(prefix, *args):
    return subprocess.run(prefix + list(args), text=True, capture_output=True, timeout=10)


def wait_for_file(path, process):
    deadline = time.monotonic() + 8
    while not path.exists():
        assert process.poll() is None, process.communicate()
        assert time.monotonic() < deadline, "test check did not reach its barrier"
        time.sleep(.01)


def blocked_check(prefix, root, name, exit_code=0):
    started, release = root / (name + "-started"), root / (name + "-release")
    # A bounded barrier establishes ordering; no latency-sensitive sleeps in assertions.
    code = (
        "from pathlib import Path; import time,os\n"
        f"Path({str(started) + '-pid'!r}).write_text(str(os.getpid()))\n"
        f"Path({str(started)!r}).touch()\n"
        "deadline=time.monotonic()+8\n"
        f"while not Path({str(release)!r}).exists():\n"
        "    if time.monotonic()>deadline: raise SystemExit(99)\n"
        "    time.sleep(.01)\n"
        f"raise SystemExit({exit_code})\n"
    )
    path = check_file(root, name, code)
    process = subprocess.Popen(prefix + ["run-checks", "--workflow-id", "adaptive", "--checks-file", str(path)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    wait_for_file(started, process)
    return process, release


def release_check(process, release):
    release.touch()
    out, err = process.communicate(timeout=10)
    return process.returncode, out + err


def test_ready_and_unrelated_registration_do_not_wait_for_checks(managed):
    prefix = setup_checks(managed)
    _, project, root, _ = managed
    process, release = blocked_check(prefix, root, "slow")
    try:
        response = run_cli(prefix, "ready", "--workflow-id", "adaptive")
        assert response.returncode == 0 and process.poll() is None, response.stderr
        assert json.loads(response.stdout)["ready"] == []
        task = root / "later.md"
        task.write_text(Path(managed[0]["tasks"]["work"]["taskFile"]).read_text())
        response = run_cli(prefix, "register-task", "--workflow-id", "adaptive", "--task-id", "later", "--role", "researcher", "--task-file", str(task), "--scope", "docs", "--parallel")
        assert response.returncode == 0 and process.poll() is None, response.stderr
    finally:
        code, output = release_check(process, release)
    assert code != 0 and "Workflow changed during checks" in output
    assert not w.load_workflow(root, "adaptive").get("checkEvidence")


@pytest.mark.parametrize("older_failure", [False, True])
def test_concurrent_check_is_rejected_without_invalidating_active_run(managed, older_failure):
    prefix = setup_checks(managed)
    root = managed[2]
    process, release = blocked_check(prefix, root, "older", int(older_failure))
    try:
        saved = w.load_workflow(root, "adaptive")
        marker = root / "must-not-execute"
        newer = check_file(root, "newer", f"from pathlib import Path; Path({str(marker)!r}).touch()")
        response = run_cli(prefix, "run-checks", "--workflow-id", "adaptive", "--checks-file", str(newer))
        assert response.returncode != 0 and "workflow lock" in response.stderr
        assert process.poll() is None and not marker.exists()
        assert w.load_workflow(root, "adaptive") == saved
    finally:
        code, output = release_check(process, release)
    assert (code != 0) == older_failure, output
    response = run_cli(prefix, "run-checks", "--workflow-id", "adaptive", "--checks-file", str(newer))
    assert response.returncode == 0 and marker.exists(), response.stderr


def test_source_change_during_checks_is_rejected(managed):
    prefix = setup_checks(managed)
    _, project, root, _ = managed
    process, release = blocked_check(prefix, root, "change")
    try:
        (project / "app.py").write_text("value=2\n")
    finally:
        code, output = release_check(process, release)
    assert code != 0 and "source inputs" in output
    assert not w.load_workflow(root, "adaptive").get("checkEvidence")


def test_pending_checks_block_both_acceptance_profiles_and_main_review(managed):
    prefix = setup_checks(managed)
    root = managed[2]
    process, release = blocked_check(prefix, root, "pending")
    try:
        flow = w.load_workflow(root, "adaptive")
        for profile in ["standard", "strict"]:
            flow["policy"]["profile"] = profile
            with pytest.raises(ValueError, match="Checks are still running"):
                w.verify_workflow(flow)
        review = root / "review.md"
        review.write_text("Review cannot run before checks complete.")
        response = run_cli(prefix, "record-main-review", "--workflow-id", "adaptive", "--review-file", str(review))
        assert response.returncode != 0 and "Checks are still running" in response.stderr
    finally:
        code, output = release_check(process, release)
    assert code == 0, output


@pytest.mark.skipif(os.name == "nt", reason="POSIX process group termination")
def test_killed_check_cannot_leave_accepted_evidence_and_fresh_checks_recover(managed):
    prefix = setup_checks(managed)
    root = managed[2]
    process, release = blocked_check(prefix, root, "killed")
    os.killpg(process.pid, signal.SIGKILL)
    child_pid = int((root / "killed-started-pid").read_text())
    try:
        os.kill(child_pid, 0)  # The actual check survives the CLI's SIGKILL.
        process.wait(timeout=5)
        flow = w.load_workflow(root, "adaptive")
        assert flow.get("checkExecution") and not flow.get("checkEvidence")
        with pytest.raises(ValueError, match="unresolved"):
            w.verify_workflow(flow)
        marker = root / "recovery-started"
        path = check_file(root, "recovery", f"from pathlib import Path; Path({str(marker)!r}).touch()")
        response = run_cli(prefix, "run-checks", "--workflow-id", "adaptive", "--checks-file", str(path))
        assert response.returncode != 0 and "workflow lock" in response.stderr
        assert not marker.exists() and w.load_workflow(root, "adaptive") == flow
    finally:
        os.killpg(child_pid, signal.SIGKILL)
        process.communicate(timeout=5)
    response = run_cli(prefix, "run-checks", "--workflow-id", "adaptive", "--checks-file", str(path))
    assert response.returncode == 0, response.stderr
    flow = w.load_workflow(root, "adaptive")
    assert not flow.get("checkExecution") and flow.get("checkEvidence")


def test_lockless_ready_does_not_authorize_stale_dispatch(managed, capsys):
    flow, _, root, _ = managed
    register(managed, parallel=True)
    w.write_workflow(root, flow)
    prefix = ["--artifact-root", str(root)]
    with w.workflow_lock(root, "adaptive"):
        assert main(prefix + ["ready", "--workflow-id", "adaptive"]) == 0
    assert json.loads(capsys.readouterr().out)["ready"] == ["work"]
    flow["policy"]["mainScopes"] = ["app.py"]
    w.write_workflow(root, flow)
    with pytest.raises(SystemExit):
        main(prefix + ["prepare-spawn", "--workflow-id", "adaptive", "--task-id", "work"])
    assert not w.load_workflow(root, "adaptive")["tasks"]["work"]["prepared"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal cancellation")
def test_sigterm_cleans_up_check_child_and_evidence(managed):
    prefix = setup_checks(managed)
    root = managed[2]
    process, _ = blocked_check(prefix, root, "cancelled")
    child_pid = int((root / "cancelled-started-pid").read_text())
    process.terminate()
    _, err = process.communicate(timeout=5)
    assert process.returncode != 0 and "cancelled" in err
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)
    flow = w.load_workflow(root, "adaptive")
    assert not flow.get("checkEvidence") and not flow.get("checkExecution")


@pytest.mark.parametrize("failure", ["nonzero", "timeout", "missing-command"])
def test_second_check_failure_never_commits_partial_success(managed, failure):
    prefix = setup_checks(managed)
    root = managed[2]
    bad = {
        "nonzero": {"argv": [sys.executable, "-c", "raise SystemExit(4)"]},
        "timeout": {"argv": [sys.executable, "-c", "import time; time.sleep(10)"], "timeoutSeconds": .1},
        "missing-command": {"argv": [str(root / "missing-command")]},
    }[failure]
    path = check_file(root, "two")
    data = json.loads(path.read_text())
    data["checks"].append(bad)
    path.write_text(json.dumps(data))
    response = run_cli(prefix, "run-checks", "--workflow-id", "adaptive", "--checks-file", str(path))
    assert response.returncode != 0
    saved = w.load_workflow(root, "adaptive")
    assert not saved.get("checkEvidence") and not saved.get("checkExecution")
    assert not saved.get("mainReview")
    assert saved.get("checkFailure")


@pytest.mark.parametrize("profile", ["standard", "strict"])
def test_failed_extra_checks_block_previously_valid_acceptance_until_rechecked(managed, profile):
    from codex_native_agents_runtime.checks import run_workflow_checks

    flow, _, root, _ = managed
    flow["policy"]["profile"] = profile
    register(managed)
    finish(managed)
    if profile == "strict":
        for kind in ["spec", "quality"]:
            register(managed, kind, role="reviewer", writable=False,
                     review_for_task_id="work", review_kind=kind)
            finish(managed, kind, kind + "-agent")
        register(managed, "final", role="final-verifier", writable=False)
        finish(managed, "final", "final-agent")
    w.write_workflow(root, flow)
    good = check_file(root, "good")
    review = root / "review.md"
    review.write_text("Reviewed the fixture source, completed attempts and checks.")
    review_args = ["--artifact-root", str(root), "record-main-review", "--workflow-id", "adaptive", "--review-file", str(review)]
    run_workflow_checks(root, "adaptive", good)
    assert main(review_args) == 0
    assert w.verify_workflow(w.load_workflow(root, "adaptive"))["status"] == "accepted"

    with pytest.raises(ValueError, match="Verification failed"):
        run_workflow_checks(root, "adaptive", check_file(root, "failed", "raise SystemExit(4)"))
    failed = w.load_workflow(root, "adaptive")
    assert failed.get("checkFailure") and not failed.get("checkExecution")
    with pytest.raises(ValueError, match="Checks failed"):
        w.verify_workflow(failed)
    with pytest.raises(SystemExit):
        main(review_args)

    run_workflow_checks(root, "adaptive", good)
    assert main(review_args) == 0
    recovered = w.load_workflow(root, "adaptive")
    assert not recovered.get("checkFailure")
    assert w.verify_workflow(recovered)["status"] == "accepted"


@pytest.mark.parametrize("mutation", ["source", "run", "policy"])
def test_changes_between_check_completion_and_commit_are_rejected(managed, monkeypatch, mutation):
    from codex_native_agents_runtime.checks import run_workflow_checks

    setup_checks(managed)
    _, project, root, _ = managed
    original = evidence.run_checks

    def race(*args, **kwargs):
        result = original(*args, **kwargs)
        if mutation == "source":
            (project / "app.py").write_text("value=changed\n")
        else:
            with w.workflow_lock(root, "adaptive"):
                flow = w.load_workflow(root, "adaptive")
                if mutation == "run":
                    flow["tasks"]["work"]["latestRunId"] = "different-run"
                else:
                    flow["policy"]["host"]["maxAgents"] = 1
                w.write_workflow(root, flow)
        return result

    monkeypatch.setattr(evidence, "run_checks", race)
    with pytest.raises(ValueError, match="changed"):
        run_workflow_checks(root, "adaptive", check_file(root, "race"))
    saved = w.load_workflow(root, "adaptive")
    assert not saved.get("checkEvidence") and not saved.get("checkExecution")


@pytest.mark.parametrize("older_failure", [False, True])
def test_late_result_cannot_replace_other_generation_state(managed, monkeypatch, older_failure):
    from codex_native_agents_runtime.checks import run_workflow_checks

    setup_checks(managed)
    root = managed[2]
    original = evidence.run_checks
    replacement = {}

    def race(*args, **kwargs):
        result = original(*args, **kwargs)
        # Simulate a recovery/migration writing a different generation, without
        # presenting manufactured state as real acceptance evidence.
        with w.workflow_lock(root, "adaptive"):
            current = w.load_workflow(root, "adaptive")
            current["checkExecution"] = {"id": "replacement-generation"}
            current["mainReview"] = {"text": "replacement marker"}
            w.write_workflow(root, current)
            replacement.update(current)
        if older_failure:
            raise ValueError("Older verification failed")
        return result

    monkeypatch.setattr(evidence, "run_checks", race)
    with pytest.raises(ValueError):
        run_workflow_checks(root, "adaptive", check_file(root, "stale"))
    assert w.load_workflow(root, "adaptive") == replacement
