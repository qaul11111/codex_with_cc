"""Offline fixtures for admission, evidence and acceptance; no model is invoked."""

import copy
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
        "models": {
            "gpt-6-astra": ["low", "medium", "high", "xhigh"],
            "gpt-6-sol": ["low", "medium", "high", "xhigh"],
            "gpt-6-luna": ["low", "medium", "high", "xhigh"],
        },
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


def transcript(managed, task_id, agent, *, effort=None, aborted=False, status="DONE"):
    flow, project, root, home = managed
    task = flow["tasks"][task_id]
    now = datetime.now(timezone.utc).isoformat()
    report = compliant_native_report(status, task["role"])
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
                "model": task["requestedModel"],
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
    w.record_spawn(flow, task_id=task_id, agent_id=agent, actual_model=flow["tasks"][task_id]["requestedModel"])
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
            "model": "gpt-6-sol",
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
        ("simple", True, False, 10, "native"),
        ("simple", True, False, 1, "main"),
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
    managed[0]["policy"]["host"]["models"]["gpt-6-sol"] = ["low"]
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
    w.record_spawn(flow, task_id="work", agent_id="agent", actual_model=flow["tasks"]["work"]["requestedModel"])
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
    path.write_text(path.read_text().replace(flow["tasks"]["work"]["requestedModel"], "other-model"))
    with pytest.raises(ValueError, match="evidence changed"):
        evidence.recheck_terminal(saved, flow["policy"]["projectRoot"])


@pytest.mark.parametrize(
    "variant, accepted",
    [
        ("matching_receipt", True),
        ("no_receipt", False),
        ("different_receipt", False),
        ("commentary", False),
        ("previous_turn", False),
        ("superseded_final", False),
        ("matching_id_wrong_receipt", False),
        ("abort_then_complete", False),
        ("later_matching_receipt", False),
    ],
)
def test_relay_final_requires_matching_host_completion(managed, variant, accepted):
    flow, project, root, home = managed
    register(managed)
    planning.prepare_spawn(flow, "work")
    w.record_spawn(
        flow, task_id="work", agent_id="agent",
        actual_model=flow["tasks"]["work"]["requestedModel"],
    )
    path, report = transcript(managed, "work", "agent")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    message = rows[3]["payload"]
    message["internal_chat_message_metadata_passthrough"] = {"turn_id": "upstream"}
    rows[4]["payload"]["last_agent_message"] = report
    if variant == "no_receipt":
        del rows[4]["payload"]["last_agent_message"]
    elif variant in {"different_receipt", "matching_id_wrong_receipt"}:
        rows[4]["payload"]["last_agent_message"] = "different report"
        if variant == "matching_id_wrong_receipt":
            message["internal_chat_message_metadata_passthrough"]["turn_id"] = "one"
    elif variant == "commentary":
        message["phase"] = "commentary"
    elif variant == "previous_turn":
        next_start = copy.deepcopy(rows[1])
        next_start["payload"]["turn_id"] = "two"
        rows[4]["payload"]["turn_id"] = "two"
        rows[4:4] = [next_start, copy.deepcopy(rows[2])]
    elif variant == "superseded_final":
        later = copy.deepcopy(rows[3])
        later["payload"]["content"][0]["text"] = "new final"
        rows.insert(4, later)
    elif variant == "abort_then_complete":
        aborted = copy.deepcopy(rows[4])
        aborted["payload"]["type"] = "turn_aborted"
        rows.insert(4, aborted)
    elif variant == "later_matching_receipt":
        rows.append(copy.deepcopy(rows[4]))
        rows[4]["payload"]["last_agent_message"] = "different report"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    if accepted:
        run = w.record_run(
            flow, task_id="work", agent_id="agent", report=report, transcript_path=path
        )
        assert run["hostEvidence"]["final"] == report
        assert run["hostEvidence"]["turnId"] == "one"
    else:
        with pytest.raises(ValueError, match="original host final"):
            w.record_run(
                flow, task_id="work", agent_id="agent", report=report, transcript_path=path
            )


def test_unprepared_route_and_model_substitution_rejected(managed):
    flow = managed[0]
    register(managed)
    with pytest.raises(ValueError, match="prepare-spawn"):
        w.record_spawn(flow, task_id="work", agent_id="a", actual_model=flow["tasks"]["work"]["requestedModel"])
    planning.prepare_spawn(flow, "work")
    with pytest.raises(ValueError, match="Prepared execution"):
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
    w.record_spawn(flow, task_id="work", agent_id="agent", actual_model=flow["tasks"]["work"]["requestedModel"])
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


def test_retry_escalates_model_once_and_gets_unique_task_name(managed):
    flow = managed[0]
    register(managed)
    first = planning.prepare_spawn(flow, "work")
    w.record_spawn(flow, task_id="work", agent_id="a", actual_model=flow["tasks"]["work"]["requestedModel"])
    path, _ = transcript(managed, "work", "a", aborted=True)
    w.record_close(
        flow, task_id="work", agent_id="a", status="unsupported", transcript_path=path
    )
    second = planning.prepare_spawn(flow, "work", escalate=True)
    assert second["task_name"] != first["task_name"]
    assert (
        first["model"] == "gpt-6-sol" and second["model"] == "gpt-6-astra"
        and first["reasoning_effort"] == "medium" and second["reasoning_effort"] == "xhigh"
    )
    w.record_spawn(flow, task_id="work", agent_id="b", actual_model=flow["tasks"]["work"]["requestedModel"])
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
    w.record_spawn(flow, task_id="work", agent_id="agent", actual_model=flow["tasks"]["work"]["requestedModel"])
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


def test_available_catalog_is_recorded_without_model_alias_substitution(managed):
    flow = managed[0]
    flow["policy"]["host"]["models"] = {
        "gpt-5.6-sol": ["low", "medium", "high"],
        "gpt-5.6-luna": ["low", "medium"],
        "gpt-6-astra": ["xhigh"],
    }
    task = register(managed, role="researcher", writable=False, complexity="simple")
    assert task["preferredModelProfile"] == "economy"
    assert task["modelProfile"] == "frontier"
    assert task["requestedModel"] == "gpt-6-astra"
    assert task["modelProfileOverride"] is None
    assert task["routingReason"]
    payload = planning.prepare_spawn(flow, "work")
    assert payload["model"] == "gpt-6-astra"
    assert task["prepared"]["routing"]["preferredModelProfile"] == "economy"


def test_no_supported_route_returns_to_main_without_registering_blocked_work(managed):
    flow = managed[0]
    flow["policy"]["host"]["models"] = {"gpt-5.6-sol": ["medium"]}
    before = copy.deepcopy(flow)
    with pytest.raises(ValueError, match="return to main"):
        register(managed)
    assert flow == before
    assert flow["tasks"] == {}


def test_explicit_unavailable_profile_is_preserved_without_stronger_replacement(managed):
    flow = managed[0]
    del flow["policy"]["host"]["models"]["gpt-6-sol"]
    before = copy.deepcopy(flow)
    with pytest.raises(ValueError, match="return to main"):
        register(managed, model_profile="balanced")
    assert flow == before


def test_explicit_profile_does_not_escalate_after_interruption(managed):
    flow = managed[0]
    task = register(managed, model_profile="balanced")
    payload = planning.prepare_spawn(flow, "work")
    w.record_spawn(flow, task_id="work", agent_id="first", actual_model=payload["model"])
    path, _ = transcript(managed, "work", "first", aborted=True)
    w.record_close(flow, task_id="work", agent_id="first", status="unsupported", transcript_path=path)
    before = copy.deepcopy(flow)
    with pytest.raises(ValueError, match="Explicit model profile is fixed"):
        planning.prepare_spawn(flow, "work", escalate=True)
    assert flow == before
    assert task["modelProfileOverride"] == "balanced"


def test_failed_escalation_preparation_is_atomic(managed):
    flow = managed[0]
    task = register(managed)
    payload = planning.prepare_spawn(flow, "work")
    w.record_spawn(flow, task_id="work", agent_id="first", actual_model=payload["model"])
    path, _ = transcript(managed, "work", "first", aborted=True)
    w.record_close(flow, task_id="work", agent_id="first", status="unsupported", transcript_path=path)
    Path(task["taskFile"]).write_text("changed task")
    before = copy.deepcopy(flow)
    with pytest.raises(ValueError, match="Registered TaskFile changed"):
        planning.prepare_spawn(flow, "work", escalate=True)
    assert flow == before
    assert task["requestedModel"] == "gpt-6-sol"


def test_each_attempt_retains_its_model_effort_and_route_evidence(managed):
    flow = managed[0]
    task = register(managed, role="researcher", writable=False, complexity="simple")
    first = planning.prepare_spawn(flow, "work")
    w.record_spawn(flow, task_id="work", agent_id="first", actual_model=first["model"])
    path, report = transcript(managed, "work", "first", status="FAIL")
    first_run = w.record_run(flow, task_id="work", agent_id="first", report=report, transcript_path=path)
    w.record_close(flow, task_id="work", agent_id="first", status="unsupported", transcript_path=path)
    second = planning.prepare_spawn(flow, "work", escalate=True)
    second_spawn = w.record_spawn(flow, task_id="work", agent_id="second", actual_model=second["model"])
    assert (first["model"], first["reasoning_effort"]) == ("gpt-6-luna", "low")
    assert (second["model"], second["reasoning_effort"]) == ("gpt-6-sol", "medium")
    assert first_run["requestedModel"] == "gpt-6-luna"
    assert first_run["reasoningEffort"] == "low"
    assert first_run["spawn"]["prepared"]["routing"]["model"] == "gpt-6-luna"
    assert second_spawn["requestedModel"] == "gpt-6-sol"
    assert second_spawn["preferredModelProfile"] == "economy"
    assert task["modelProfile"] == "balanced"


def test_preparation_rechecks_model_availability_without_mutation(managed):
    flow = managed[0]
    task = register(managed)
    del flow["policy"]["host"]["models"]["gpt-6-sol"]
    before = copy.deepcopy(flow)
    with pytest.raises(ValueError, match="Model/effort unavailable"):
        planning.prepare_spawn(flow, "work")
    assert flow == before
    assert task["requestedModel"] == "gpt-6-sol"


def test_changed_route_after_preparation_is_rejected(managed):
    flow = managed[0]
    task = register(managed)
    planning.prepare_spawn(flow, "work")
    task["requestedModel"] = "gpt-6-astra"
    with pytest.raises(ValueError, match="route changed after preparation"):
        w.record_spawn(flow, task_id="work", agent_id="agent", actual_model="gpt-6-astra")
    assert task["latestSpawn"] is None


@pytest.mark.parametrize("models", [None, [], {"": ["low"]}, {"gpt-6-sol": "medium"}, {"gpt-6-sol": [3]}, {"gpt-6-sol": [["medium"]]}, {"gpt-6-sol": ["medium", "medium"]}])
def test_malformed_model_catalog_is_rejected(managed, models):
    caps = copy.deepcopy(managed[0]["policy"]["host"])
    caps["models"] = models
    with pytest.raises(ValueError, match="Host models"):
        evidence.validate_capabilities(caps)


def test_catalog_accepts_luna_only_and_unknown_models(managed):
    caps = copy.deepcopy(managed[0]["policy"]["host"])
    caps["models"] = {"gpt-6-luna": ["low"], "future-model": ["future-effort"]}
    assert evidence.validate_capabilities(caps)["models"] == caps["models"]


def test_route_cli_is_read_only_and_respects_explicit_selection(managed, capsys):
    flow, project, root, _ = managed
    caps = root / "caps.json"
    caps.write_text(json.dumps(flow["policy"]["host"]))
    before = sorted(project.rglob("*"))
    assert main(["route", "--role", "researcher", "--complexity", "simple", "--host-capabilities", str(caps)]) == 0
    route = json.loads(capsys.readouterr().out)
    assert route["model"] == "gpt-6-luna"
    assert route["reasoning_effort"] == "low"
    assert route["preferred_profile"] == "economy"
    assert route["reason"]
    assert sorted(project.rglob("*")) == before
    caps.write_text(json.dumps({**flow["policy"]["host"], "models": {"gpt-6-astra": ["xhigh"]}}))
    assert main(["route", "--role", "implementer", "--host-capabilities", str(caps), "--model-profile", "balanced"]) == 0
    route = json.loads(capsys.readouterr().out)
    assert route["model"] is None
    assert route["fallback"] == "main_thread"
    assert not list(root.glob("workflow_*.json"))


@pytest.mark.parametrize("at_frontier", [False, True])
def test_no_available_escalation_keeps_original_attempt_and_route(managed, at_frontier):
    flow = managed[0]
    task = register(
        managed,
        role="planner" if at_frontier else "implementer",
        writable=not at_frontier,
        complexity="complex" if at_frontier else "normal",
    )
    first = planning.prepare_spawn(flow, "work")
    w.record_spawn(
        flow, task_id="work", agent_id="first", actual_model=first["model"]
    )
    path, _ = transcript(managed, "work", "first", aborted=True)
    w.record_close(
        flow,
        task_id="work",
        agent_id="first",
        status="unsupported",
        transcript_path=path,
    )
    if not at_frontier:
        del flow["policy"]["host"]["models"]["gpt-6-astra"]
    before = copy.deepcopy(flow)
    with pytest.raises(ValueError, match="return to main"):
        planning.prepare_spawn(flow, "work", escalate=True)
    assert flow == before
    assert planning.ready_tasks(flow)["ready"] == []
    assert planning.ready_tasks(flow)["requiresEscalation"] == []
    assert len(task["spawnAttempts"]) == 1
    assert task["prepared"] is None


@pytest.mark.parametrize("profile", [None, "balanced", "frontier"])
def test_retry_cannot_bypass_escalation_and_ready_reports_required_action(managed, profile):
    flow = managed[0]
    task = register(managed, model_profile=profile)
    first = planning.prepare_spawn(flow, "work")
    w.record_spawn(flow, task_id="work", agent_id="first", actual_model=first["model"])
    path, _ = transcript(managed, "work", "first", aborted=True)
    w.record_close(
        flow, task_id="work", agent_id="first", status="unsupported", transcript_path=path
    )
    before = copy.deepcopy(flow)
    with pytest.raises(ValueError, match="retry requires --escalate"):
        planning.prepare_spawn(flow, "work")
    assert flow == before
    ready = planning.ready_tasks(flow)
    assert ready["ready"] == []
    assert ready["requiresEscalation"] == (["work"] if profile is None else [])
    assert task["prepared"] is None


def test_escalation_wave_reserves_the_same_concurrency_slots(managed):
    flow = managed[0]
    flow["policy"]["host"]["maxAgents"] = 1
    register(managed, parallel=True)
    first = planning.prepare_spawn(flow, "work")
    w.record_spawn(flow, task_id="work", agent_id="first", actual_model=first["model"])
    path, _ = transcript(managed, "work", "first", aborted=True)
    w.record_close(
        flow, task_id="work", agent_id="first", status="unsupported", transcript_path=path
    )
    register(managed, "next", role="researcher", scopes=("docs",), writable=False, parallel=True)
    wave = planning.ready_tasks(flow)
    assert wave["requiresEscalation"] == ["work"]
    assert wave["ready"] == []
    assert "concurrency limit" in wave["blocked"]["next"]
