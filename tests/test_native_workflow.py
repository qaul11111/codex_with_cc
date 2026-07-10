from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.task_helpers import compliant_native_report, compliant_native_task


REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "skills" / "codex-native-agents" / "scripts"
CLI = SCRIPTS / "native_agents.py"
sys.path.insert(0, str(SCRIPTS))

from codex_native_agents_runtime import workflow as workflow_runtime
from codex_native_agents_runtime.workflow import (
    WorkflowError,
    new_workflow,
    record_run,
    register_task,
    verify_workflow,
)


def run_cli(artifact_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), "--artifact-root", str(artifact_root), *args],
        cwd=REPO,
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONNOUSERSITE": "1"},
        check=False,
    )


def write_task(tmp_path: Path, name: str) -> Path:
    task_file = tmp_path / f"{name}.md"
    task_file.write_text(compliant_native_task(), encoding="utf-8")
    return task_file


def write_report(tmp_path: Path, name: str, role: str) -> Path:
    report_file = tmp_path / f"{name}.md"
    report_file.write_text(compliant_native_report("DONE", role), encoding="utf-8")
    return report_file


def register_cli_task(
    artifact_root: Path,
    workflow_id: str,
    task_id: str,
    role: str,
    task_file: Path,
    *extra_args: str,
) -> subprocess.CompletedProcess[str]:
    return run_cli(
        artifact_root,
        "register-task",
        "--workflow-id",
        workflow_id,
        "--task-id",
        task_id,
        "--role",
        role,
        "--task-file",
        str(task_file),
        "--scope",
        "skills/codex-native-agents",
        "--writable",
        *extra_args,
    )


def record_cli_run(
    artifact_root: Path,
    workflow_id: str,
    task_id: str,
    report_file: Path,
) -> subprocess.CompletedProcess[str]:
    return run_cli(
        artifact_root,
        "record-run",
        "--workflow-id",
        workflow_id,
        "--task-id",
        task_id,
        "--agent-id",
        f"agent-{task_id}",
        "--report-file",
        str(report_file),
    )


def add_accepted_reviews(workflow: dict, task_id: str = "impl") -> None:
    for kind in ("spec", "quality"):
        reviewer_task_id = f"{kind}-review"
        register_task(
            workflow,
            task_id=reviewer_task_id,
            role="reviewer",
            scopes=(f"reviews/{kind}",),
            writable=False,
            review_for_task_id=task_id,
            review_kind=kind,
        )
        record_run(
            workflow,
            task_id=reviewer_task_id,
            agent_id=f"agent-{reviewer_task_id}",
            report=compliant_native_report("DONE", "reviewer"),
            run_id=f"{reviewer_task_id}-run",
        )


def rerun_accepted_reviews(workflow: dict, suffix: str) -> None:
    for kind in ("spec", "quality"):
        reviewer_task_id = f"{kind}-review"
        record_run(
            workflow,
            task_id=reviewer_task_id,
            agent_id=f"agent-{reviewer_task_id}",
            report=compliant_native_report("DONE", "reviewer"),
            run_id=f"{reviewer_task_id}-{suffix}",
        )


def add_done_final_verifier(workflow: dict) -> None:
    register_task(
        workflow,
        task_id="final",
        role="final-verifier",
        scopes=("verification",),
        writable=False,
    )
    record_run(
        workflow,
        task_id="final",
        agent_id="agent-final",
        report=compliant_native_report("DONE", "final-verifier"),
        run_id="final-run",
    )


def ready_for_acceptance_workflow() -> dict:
    workflow = new_workflow("wf-accepted")
    register_task(workflow, task_id="impl", role="implementer", scopes=("src",), writable=True)
    record_run(
        workflow,
        task_id="impl",
        agent_id="agent-impl",
        report=compliant_native_report("DONE", "implementer"),
        run_id="impl-run",
    )
    add_accepted_reviews(workflow)
    add_done_final_verifier(workflow)
    return workflow


def complete_workflow() -> dict:
    workflow = ready_for_acceptance_workflow()
    verify_workflow(workflow)
    return workflow


def test_implementer_requires_two_reviews_and_final_verifier() -> None:
    workflow = new_workflow("wf-gates")
    register_task(workflow, task_id="impl", role="implementer", scopes=("src",), writable=True)
    record_run(workflow, task_id="impl", agent_id="agent-impl", report=compliant_native_report("DONE", "implementer"))

    with pytest.raises(WorkflowError, match="spec review"):
        verify_workflow(workflow)


def test_record_spawn_updates_actual_model_and_inheritance_fallback() -> None:
    workflow = new_workflow("wf-spawn-evidence")
    register_task(workflow, task_id="research", role="researcher", scopes=("docs",), writable=False)

    first = workflow_runtime.record_spawn(
        workflow,
        task_id="research",
        agent_id="agent-research",
        actual_model="host-research-model",
    )
    fallback = workflow_runtime.record_spawn(
        workflow,
        task_id="research",
        agent_id="agent-research-fallback",
        inherit_parent=True,
        fallback_reason="requested model unavailable in this host",
    )

    task = workflow["tasks"]["research"]
    assert first["actualModel"] == "host-research-model"
    assert fallback["executionMode"] == "inherit_parent"
    assert fallback["fallbackReason"] == "requested model unavailable in this host"
    assert task["requestedModel"] == "gpt-5.6-luna"
    assert task["latestSpawn"] == fallback


def test_record_spawn_requires_actual_model_or_inheritance() -> None:
    workflow = new_workflow("wf-spawn-route")
    register_task(workflow, task_id="research", role="researcher", scopes=("docs",), writable=False)

    with pytest.raises(WorkflowError, match="actual model or inherit"):
        workflow_runtime.record_spawn(workflow, task_id="research", agent_id="agent-research")


def test_cli_record_spawn_writes_actual_route_evidence(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    task_file = write_task(tmp_path, "spawn-evidence")
    assert run_cli(artifact_root, "init", "--workflow-id", "wf-cli-spawn").returncode == 0
    assert register_cli_task(artifact_root, "wf-cli-spawn", "research", "researcher", task_file).returncode == 0

    result = run_cli(
        artifact_root,
        "record-spawn",
        "--workflow-id",
        "wf-cli-spawn",
        "--task-id",
        "research",
        "--agent-id",
        "agent-research",
        "--inherit-parent",
        "--fallback-reason",
        "requested model unavailable in this host",
    )

    assert result.returncode == 0, result.stderr
    workflow = json.loads((artifact_root / "workflow_wf-cli-spawn.json").read_text(encoding="utf-8"))
    assert workflow["tasks"]["research"]["latestSpawn"]["executionMode"] == "inherit_parent"
    assert workflow["tasks"]["research"]["latestSpawn"]["fallbackReason"]


def test_verify_preserves_latest_spawn_evidence_in_final_acceptance() -> None:
    workflow = ready_for_acceptance_workflow()
    workflow_runtime.record_spawn(
        workflow,
        task_id="impl",
        agent_id="agent-impl",
        inherit_parent=True,
        fallback_reason="requested model unavailable in this host",
    )

    verify_workflow(workflow)

    evidence = workflow["finalAcceptance"]["spawnEvidence"]
    assert evidence == [{"taskId": "impl", "latestSpawn": workflow["tasks"]["impl"]["latestSpawn"]}]


def test_parallel_writable_overlap_is_rejected() -> None:
    workflow = new_workflow("wf-parallel")
    register_task(workflow, task_id="a", role="implementer", scopes=("src/auth",), writable=True, parallel=True)

    with pytest.raises(WorkflowError, match="overlap"):
        register_task(workflow, task_id="b", role="implementer", scopes=("src/auth/token.py",), writable=True, parallel=True)


def test_accepted_workflow_rejects_new_tasks_and_runs() -> None:
    workflow = complete_workflow()

    with pytest.raises(WorkflowError, match="immutable"):
        register_task(workflow, task_id="later", role="researcher", scopes=("docs",), writable=False)
    with pytest.raises(WorkflowError, match="immutable"):
        record_run(
            workflow,
            task_id="impl",
            agent_id="agent-impl-retry",
            report=compliant_native_report("DONE", "implementer"),
            run_id="impl-retry",
        )


def test_implementer_rerun_invalidates_stale_review_evidence() -> None:
    workflow = new_workflow("wf-stale-review")
    register_task(workflow, task_id="impl", role="implementer", scopes=("src",), writable=True)
    record_run(
        workflow,
        task_id="impl",
        agent_id="agent-impl",
        report=compliant_native_report("DONE", "implementer"),
        run_id="impl-v1",
    )
    add_accepted_reviews(workflow)
    record_run(
        workflow,
        task_id="impl",
        agent_id="agent-impl",
        report=compliant_native_report("DONE", "implementer"),
        run_id="impl-v2",
    )

    with pytest.raises(WorkflowError, match="current implementer run"):
        verify_workflow(workflow)


def test_final_verifier_recorded_before_reviews_cannot_pass() -> None:
    workflow = new_workflow("wf-early-final")
    register_task(workflow, task_id="impl", role="implementer", scopes=("src",), writable=True)
    record_run(
        workflow,
        task_id="impl",
        agent_id="agent-impl",
        report=compliant_native_report("DONE", "implementer"),
        run_id="impl-run",
    )
    add_done_final_verifier(workflow)
    add_accepted_reviews(workflow)

    with pytest.raises(WorkflowError, match="final verifier snapshot"):
        verify_workflow(workflow)


@pytest.mark.parametrize("rerun_kind", ["implementer", "reviewer"])
def test_reruns_invalidate_stale_final_verifier_snapshot(rerun_kind: str) -> None:
    workflow = ready_for_acceptance_workflow()
    if rerun_kind == "implementer":
        record_run(
            workflow,
            task_id="impl",
            agent_id="agent-impl",
            report=compliant_native_report("DONE", "implementer"),
            run_id="impl-rerun",
        )
        rerun_accepted_reviews(workflow, "after-impl")
    else:
        record_run(
            workflow,
            task_id="spec-review",
            agent_id="agent-spec-review",
            report=compliant_native_report("DONE", "reviewer"),
            run_id="spec-review-rerun",
        )

    with pytest.raises(WorkflowError, match="final verifier snapshot"):
        verify_workflow(workflow)


def test_cli_rejects_identifier_traversal(tmp_path: Path) -> None:
    result = run_cli(tmp_path / "artifacts", "init", "--workflow-id", "../wf")

    assert result.returncode != 0
    assert "identifier" in result.stderr.lower()


def test_cli_duplicate_init_does_not_replace_existing_workflow(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    first = run_cli(artifact_root, "init", "--workflow-id", "wf-duplicate")
    assert first.returncode == 0, first.stderr
    workflow_file = artifact_root / "workflow_wf-duplicate.json"
    original = workflow_file.read_text(encoding="utf-8")

    second = run_cli(artifact_root, "init", "--workflow-id", "wf-duplicate")

    assert second.returncode != 0
    assert "already exists" in second.stderr.lower()
    assert workflow_file.read_text(encoding="utf-8") == original


def test_cli_rejects_parallel_writable_overlap(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    task_file = write_task(tmp_path, "overlap")
    assert run_cli(artifact_root, "init", "--workflow-id", "wf-overlap").returncode == 0
    assert register_cli_task(
        artifact_root,
        "wf-overlap",
        "first",
        "implementer",
        task_file,
        "--scope",
        "src/auth",
        "--parallel",
    ).returncode == 0

    result = register_cli_task(
        artifact_root,
        "wf-overlap",
        "second",
        "implementer",
        task_file,
        "--scope",
        "src/auth/token.py",
        "--parallel",
    )

    assert result.returncode != 0
    assert "overlap" in result.stderr.lower()


def test_cli_verify_fails_before_required_reviews(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    task_file = write_task(tmp_path, "implementer")
    report_file = write_report(tmp_path, "implementer-report", "implementer")
    assert run_cli(artifact_root, "init", "--workflow-id", "wf-pre-review").returncode == 0
    assert register_cli_task(artifact_root, "wf-pre-review", "impl", "implementer", task_file).returncode == 0
    assert record_cli_run(artifact_root, "wf-pre-review", "impl", report_file).returncode == 0

    result = run_cli(artifact_root, "verify", "--workflow-id", "wf-pre-review")

    assert result.returncode != 0
    assert "spec review" in result.stderr.lower()


def test_cli_verify_fails_before_final_verifier(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    task_file = write_task(tmp_path, "gate")
    assert run_cli(artifact_root, "init", "--workflow-id", "wf-pre-final").returncode == 0
    assert register_cli_task(artifact_root, "wf-pre-final", "impl", "implementer", task_file).returncode == 0
    assert record_cli_run(artifact_root, "wf-pre-final", "impl", write_report(tmp_path, "impl-report", "implementer")).returncode == 0
    for kind in ("spec", "quality"):
        reviewer_task_id = f"{kind}-review"
        assert register_cli_task(
            artifact_root,
            "wf-pre-final",
            reviewer_task_id,
            "reviewer",
            task_file,
            "--review-for-task-id",
            "impl",
            "--review-kind",
            kind,
        ).returncode == 0
        assert record_cli_run(
            artifact_root,
            "wf-pre-final",
            reviewer_task_id,
            write_report(tmp_path, f"{reviewer_task_id}-report", "reviewer"),
        ).returncode == 0

    result = run_cli(artifact_root, "verify", "--workflow-id", "wf-pre-final")

    assert result.returncode != 0
    assert "final verifier" in result.stderr.lower()


def test_cli_verifies_complete_implementer_workflow(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    task_file = write_task(tmp_path, "complete")
    assert run_cli(artifact_root, "init", "--workflow-id", "wf-complete").returncode == 0
    assert register_cli_task(artifact_root, "wf-complete", "impl", "implementer", task_file).returncode == 0
    assert record_cli_run(artifact_root, "wf-complete", "impl", write_report(tmp_path, "impl-report", "implementer")).returncode == 0
    for kind in ("spec", "quality"):
        reviewer_task_id = f"{kind}-review"
        assert register_cli_task(
            artifact_root,
            "wf-complete",
            reviewer_task_id,
            "reviewer",
            task_file,
            "--review-for-task-id",
            "impl",
            "--review-kind",
            kind,
        ).returncode == 0
        assert record_cli_run(
            artifact_root,
            "wf-complete",
            reviewer_task_id,
            write_report(tmp_path, f"{reviewer_task_id}-report", "reviewer"),
        ).returncode == 0
    assert register_cli_task(artifact_root, "wf-complete", "final", "final-verifier", task_file).returncode == 0
    assert record_cli_run(artifact_root, "wf-complete", "final", write_report(tmp_path, "final-report", "final-verifier")).returncode == 0

    result = run_cli(artifact_root, "verify", "--workflow-id", "wf-complete")

    assert result.returncode == 0, result.stderr
    workflow = json.loads((artifact_root / "workflow_wf-complete.json").read_text(encoding="utf-8"))
    assert workflow["status"] == "accepted"
    assert workflow["finalAcceptance"]["status"] == "accepted"
    assert workflow["tasks"]["impl"]["reviews"]["spec"]["decision"] == "accepted"
    assert workflow["tasks"]["impl"]["reviews"]["quality"]["decision"] == "accepted"


def test_concurrent_cli_record_runs_preserve_both_runs(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    task_file = write_task(tmp_path, "concurrent")
    assert run_cli(artifact_root, "init", "--workflow-id", "wf-concurrent").returncode == 0
    for task_id in ("one", "two"):
        assert register_cli_task(artifact_root, "wf-concurrent", task_id, "researcher", task_file).returncode == 0
    commands = [
        [
            sys.executable,
            str(CLI),
            "--artifact-root",
            str(artifact_root),
            "record-run",
            "--workflow-id",
            "wf-concurrent",
            "--task-id",
            task_id,
            "--agent-id",
            f"agent-{task_id}",
            "--report-file",
            str(write_report(tmp_path, f"{task_id}-report", "researcher")),
        ]
        for task_id in ("one", "two")
    ]
    processes = [
        subprocess.Popen(command, cwd=REPO, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**os.environ, "PYTHONNOUSERSITE": "1"})
        for command in commands
    ]
    results = [process.communicate(timeout=10) for process in processes]

    assert all(process.returncode == 0 for process in processes), results
    workflow = json.loads((artifact_root / "workflow_wf-concurrent.json").read_text(encoding="utf-8"))
    assert {run["taskId"] for run in workflow["runs"].values()} == {"one", "two"}
    assert workflow["revision"] == 4


@pytest.mark.parametrize("started_at", ["not-a-timestamp", "2026-07-10T12:00:00"])
def test_cli_rejects_invalid_or_naive_started_at(tmp_path: Path, started_at: str) -> None:
    artifact_root = tmp_path / "artifacts"
    task_file = write_task(tmp_path, "timestamp")
    assert run_cli(artifact_root, "init", "--workflow-id", "wf-timestamp").returncode == 0
    assert register_cli_task(artifact_root, "wf-timestamp", "research", "researcher", task_file).returncode == 0

    result = run_cli(
        artifact_root,
        "record-run",
        "--workflow-id",
        "wf-timestamp",
        "--task-id",
        "research",
        "--agent-id",
        "agent-research",
        "--report-file",
        str(write_report(tmp_path, "timestamp-report", "researcher")),
        "--started-at",
        started_at,
    )

    assert result.returncode != 0
    assert "timezone-aware" in result.stderr.lower()
