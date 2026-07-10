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


def test_implementer_requires_two_reviews_and_final_verifier() -> None:
    workflow = new_workflow("wf-gates")
    register_task(workflow, task_id="impl", role="implementer", scopes=("src",), writable=True)
    record_run(workflow, task_id="impl", agent_id="agent-impl", report=compliant_native_report("DONE", "implementer"))

    with pytest.raises(WorkflowError, match="spec review"):
        verify_workflow(workflow)


def test_parallel_writable_overlap_is_rejected() -> None:
    workflow = new_workflow("wf-parallel")
    register_task(workflow, task_id="a", role="implementer", scopes=("src/auth",), writable=True, parallel=True)

    with pytest.raises(WorkflowError, match="overlap"):
        register_task(workflow, task_id="b", role="implementer", scopes=("src/auth/token.py",), writable=True, parallel=True)


def test_cli_rejects_identifier_traversal(tmp_path: Path) -> None:
    result = run_cli(tmp_path / "artifacts", "init", "--workflow-id", "../wf")

    assert result.returncode != 0
    assert "identifier" in result.stderr.lower()


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
