from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .common import ARTIFACT_SCHEMA_VERSION, INVOCATION_CONTRACT, WORKER_ROLES, DelegateError, now_iso
from .io_utils import load_json, write_json
from .locks import acquire_file_lock
from .reports import parse_report_final_result, parse_report_role, parse_report_status, report_summary_line


REQUIRED_IMPLEMENTER_REVIEWS = ("spec", "quality")


def safe_workflow_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", value.strip())
    return safe or "workflow"


def safe_task_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", value.strip())
    return safe or "task"


def workflow_path(artifact_root: Path | str, workflow_id: str) -> Path:
    return Path(artifact_root).resolve() / f"workflow_{safe_workflow_id(workflow_id)}.json"


def workflow_lock_path(artifact_root: Path | str, workflow_id: str) -> Path:
    return Path(artifact_root).resolve() / f".workflow_{safe_workflow_id(workflow_id)}.lock"


def normalize_role(role: str) -> str:
    value = role.strip().lower()
    if value not in WORKER_ROLES:
        expected = ", ".join(WORKER_ROLES)
        raise ValueError(f"invalid role: {role!r} (choose from {expected})")
    return value


def empty_workflow(workflow_id: str) -> dict[str, Any]:
    now = now_iso()
    return {
        "artifactSchema": ARTIFACT_SCHEMA_VERSION,
        "invocationContract": INVOCATION_CONTRACT,
        "workflowId": workflow_id,
        "createdAt": now,
        "updatedAt": now,
        "revision": 0,
        "tasks": {},
        "runs": {},
        "agentAttempts": {},
    }


def review_decision_for(
    run_status: str,
    report_status: str,
    report_final_result: str,
    dry_run: bool = False,
) -> str:
    if dry_run:
        return "dry-run"
    if run_status != "completed":
        return "failed"
    if report_status == "DONE" and report_final_result == "DONE":
        return "accepted"
    if report_status in ("DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED"):
        return "needs-review"
    return "rejected"


def implementer_review_decision(task: dict[str, Any]) -> str:
    if task.get("dryRun"):
        return "dry-run"
    if task.get("status") != "completed":
        return "failed"
    if task.get("lastReportStatus") != "DONE" or task.get("lastReportFinalResult") != "DONE":
        return "needs-review"
    latest_run_id = str(task.get("latestRunId") or "")
    reviews = task.get("reviews") if isinstance(task.get("reviews"), dict) else {}
    missing = [
        kind
        for kind in REQUIRED_IMPLEMENTER_REVIEWS
        if not isinstance(reviews.get(kind), dict)
        or str((reviews.get(kind) or {}).get("reviewedRunId") or "") != latest_run_id
    ]
    if missing:
        return "pending-review"
    if all((reviews[kind] or {}).get("reviewDecision") == "accepted" for kind in REQUIRED_IMPLEMENTER_REVIEWS):
        return "accepted"
    return "needs-review"


def final_verifier_snapshot(workflow: dict[str, Any]) -> dict[str, Any]:
    tasks = workflow.get("tasks") if isinstance(workflow.get("tasks"), dict) else {}
    snapshot: dict[str, Any] = {}
    for task_id in sorted(tasks):
        task = tasks[task_id]
        if not isinstance(task, dict) or task.get("role") != "implementer":
            continue
        reviews = task.get("reviews") if isinstance(task.get("reviews"), dict) else {}
        snapshot[str(task_id)] = {
            "implementerRunId": task.get("latestRunId"),
            "specReviewRunId": (reviews.get("spec") or {}).get("runId"),
            "qualityReviewRunId": (reviews.get("quality") or {}).get("runId"),
        }
    return snapshot


def current_final_verifier(workflow: dict[str, Any]) -> dict[str, Any] | None:
    tasks = workflow.get("tasks") if isinstance(workflow.get("tasks"), dict) else {}
    expected_snapshot = final_verifier_snapshot(workflow)
    candidates = [
        task
        for task in tasks.values()
        if isinstance(task, dict)
        and task.get("role") == "final-verifier"
        and not task.get("dryRun")
        and task.get("status") == "completed"
        and task.get("lastReportStatus") == "DONE"
        and task.get("lastReportFinalResult") == "DONE"
        and task.get("reviewDecision") == "accepted"
        and task.get("verifiedImplementerRuns") == expected_snapshot
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda task: str(task.get("updatedAt") or ""))


def capture_final_verifier_snapshot(artifact_root: Path, workflow_id: str) -> dict[str, Any]:
    path = workflow_path(artifact_root, workflow_id)
    lock = acquire_file_lock(
        workflow_lock_path(artifact_root, workflow_id),
        timeout_seconds=30,
        poll_seconds=0.05,
        message=lambda: f"Timed out waiting to capture final-verifier snapshot: {path}",
    )
    try:
        workflow = load_json(path) if path.exists() else empty_workflow(workflow_id)
        return final_verifier_snapshot(workflow)
    finally:
        lock.release()


def update_workflow_acceptance(workflow: dict[str, Any]) -> None:
    tasks = workflow.get("tasks") if isinstance(workflow.get("tasks"), dict) else {}
    task_values = [task for task in tasks.values() if isinstance(task, dict)]
    dry_runs = [task.get("taskId") for task in task_values if task.get("dryRun")]
    if dry_runs:
        workflow["finalAcceptance"] = {
            "status": "dry-run",
            "reason": "dry-run artifacts are diagnostic only and cannot satisfy acceptance",
            "dryRunTasks": dry_runs,
        }
        return
    failed_tasks = [
        task.get("taskId")
        for task in task_values
        if task.get("status") == "failed"
        or task.get("lastReportStatus") == "FAIL"
        or task.get("lastReportFinalResult") == "FAIL"
        or (task.get("role") != "implementer" and task.get("reviewDecision") in ("failed", "rejected"))
    ]
    if failed_tasks:
        workflow["finalAcceptance"] = {"status": "failed", "failedTasks": failed_tasks}
        return
    pending_tasks = [
        task.get("taskId")
        for task in task_values
        if task.get("status") not in (None, "completed", "failed")
    ]
    if pending_tasks:
        workflow["finalAcceptance"] = {"status": "pending-run", "pendingTasks": pending_tasks}
        return
    needs_review_tasks = [
        task.get("taskId")
        for task in task_values
        if task.get("role") != "implementer" and task.get("reviewDecision") != "accepted"
    ]
    if needs_review_tasks:
        workflow["finalAcceptance"] = {"status": "needs-review", "pendingTasks": needs_review_tasks}
        return
    attempts = workflow.get("agentAttempts") if isinstance(workflow.get("agentAttempts"), dict) else {}
    unregistered_agents = [
        attempt.get("agentId")
        for attempt in attempts.values()
        if isinstance(attempt, dict) and not attempt.get("spawnRecordedAt")
    ]
    if unregistered_agents:
        workflow["finalAcceptance"] = {
            "status": "pending-agent-spawn",
            "reason": "every Codex child run must bind to an explicitly recorded spawn",
            "unregisteredAgentIds": unregistered_agents,
        }
        return
    open_agents = [
        attempt.get("agentId")
        for attempt in attempts.values()
        if isinstance(attempt, dict) and attempt.get("closeStatus") != "closed"
    ]
    if open_agents:
        workflow["finalAcceptance"] = {
            "status": "pending-agent-close",
            "reason": "every spawned Codex child must be closed and recorded",
            "openAgentIds": open_agents,
        }
        return
    implementers = [task for task in task_values if task.get("role") == "implementer"]
    if not implementers:
        workflow["finalAcceptance"] = {"status": "accepted", "reason": "no implementer tasks require review"}
        return
    failed = [task.get("taskId") for task in implementers if task.get("status") != "completed"]
    if failed:
        workflow["finalAcceptance"] = {"status": "failed", "failedTasks": failed}
        return
    pending = [task.get("taskId") for task in implementers if task.get("reviewDecision") != "accepted"]
    if pending:
        workflow["finalAcceptance"] = {"status": "pending-review", "pendingTasks": pending}
        return
    verifier = current_final_verifier(workflow)
    if verifier is None:
        workflow["finalAcceptance"] = {
            "status": "pending-final-verifier",
            "reason": "an accepted final-verifier run must cover the current implementer and review runs",
        }
        return
    workflow["finalAcceptance"] = {
        "status": "accepted",
        "finalVerifierTaskId": verifier.get("taskId"),
        "finalVerifierRunId": verifier.get("latestRunId"),
    }


def update_workflow_record(
    artifact_root: Path,
    workflow_id: str,
    task_id: str,
    role: str,
    scope: list[str],
    verification: list[str],
    depends_on: list[str],
    run_id: str,
    config_path: Path,
    status_path: Path,
    output_path: Path,
    prompt_path: Path,
    raw_stream_path: Path,
    trace_path: Path,
    run_status: str,
    review_for_task_id: str | None = None,
    review_kind: str | None = None,
    runner_type: str | None = None,
    review_for_run_id: str | None = None,
    dry_run: bool = False,
    codex_thread_id: str | None = None,
    verified_implementer_runs: dict[str, Any] | None = None,
) -> Path:
    path = workflow_path(artifact_root, workflow_id)
    lock = acquire_file_lock(
        workflow_lock_path(artifact_root, workflow_id),
        timeout_seconds=30,
        poll_seconds=0.05,
        message=lambda: f"Timed out waiting to update workflow artifact: {path}",
    )
    try:
        workflow = load_json(path) if path.exists() else empty_workflow(workflow_id)
        report_text = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
        report_status = parse_report_status(report_text)
        report_final_result = parse_report_final_result(report_text)
        report_role = parse_report_role(report_text)
        report_summary = report_summary_line(report_text)
        review_decision = review_decision_for(run_status, report_status, report_final_result, dry_run)
        if report_role != role and not dry_run:
            review_decision = "rejected"

        workflow["artifactSchema"] = ARTIFACT_SCHEMA_VERSION
        workflow["invocationContract"] = INVOCATION_CONTRACT
        workflow["workflowId"] = workflow_id
        workflow["updatedAt"] = now_iso()
        workflow["revision"] = int(workflow.get("revision") or 0) + 1
        workflow.setdefault("tasks", {})
        workflow.setdefault("runs", {})
        workflow.setdefault("agentAttempts", {})
        if codex_thread_id:
            attempt = workflow["agentAttempts"].setdefault(
                codex_thread_id,
                {
                    "agentId": codex_thread_id,
                    "taskId": task_id,
                    "spawnedAt": None,
                    "spawnRecordedAt": None,
                    "closeStatus": None,
                },
            )
            if attempt.get("taskId") not in (None, task_id):
                raise DelegateError(f"agent {codex_thread_id} is already bound to task {attempt.get('taskId')}")
            attempt.update(
                {
                    "taskId": task_id,
                    "runId": run_id,
                    "runStatus": run_status,
                    "runRecordedAt": now_iso(),
                }
            )

        task = workflow["tasks"].setdefault(
            task_id,
            {
                "taskId": task_id,
                "role": role,
                "scope": scope,
                "verification": verification,
                "dependsOn": depends_on,
                "runs": [],
                "status": run_status,
            },
        )
        previous_latest_run_id = task.get("latestRunId")
        task.update(
            {
                "role": role,
                "scope": scope,
                "verification": verification,
                "dependsOn": depends_on,
                "status": run_status,
                "latestRunId": run_id,
                "lastReportStatus": report_status,
                "lastReportFinalResult": report_final_result,
                "lastReportRole": report_role,
                "reviewDecision": review_decision,
                "dryRun": bool(dry_run),
                "codexThreadId": codex_thread_id,
                "updatedAt": now_iso(),
            }
        )
        task.setdefault("runs", [])
        if run_id not in task["runs"]:
            task["runs"].append(run_id)
        if role == "implementer":
            if previous_latest_run_id and previous_latest_run_id != run_id:
                task["reviews"] = {}
            else:
                task.setdefault("reviews", {})
        if role == "reviewer":
            task["reviewForTaskId"] = review_for_task_id
            task["reviewForRunId"] = review_for_run_id
            task["reviewKind"] = review_kind
        if role == "final-verifier":
            task["verifiedImplementerRuns"] = verified_implementer_runs or {}

        effective_review_decision = review_decision
        if role == "reviewer":
            target = workflow["tasks"].get(review_for_task_id) if review_for_task_id else None
            target_latest_run_id = str((target or {}).get("latestRunId") or "")
            if (
                not isinstance(target, dict)
                or target.get("role") != "implementer"
                or not review_for_run_id
                or str(review_for_run_id) != target_latest_run_id
            ):
                effective_review_decision = "stale-review"
                task["reviewDecision"] = effective_review_decision
            elif review_kind in REQUIRED_IMPLEMENTER_REVIEWS:
                reviews = target.setdefault("reviews", {})
                reviews[review_kind] = {
                    "runId": run_id,
                    "taskId": task_id,
                    "reviewedRunId": review_for_run_id,
                    "status": run_status,
                    "reportStatus": report_status,
                    "reportFinalResult": report_final_result,
                    "reportRole": report_role,
                    "reviewDecision": review_decision,
                    "dryRun": bool(dry_run),
                }
                target["reviewDecision"] = implementer_review_decision(target)

        workflow["runs"][run_id] = {
            "runId": run_id,
            "taskId": task_id,
            "role": role,
            "runnerType": runner_type,
            "status": run_status,
            "reportStatus": report_status,
            "reportFinalResult": report_final_result,
            "reportRole": report_role,
            "reportSummary": report_summary,
            "reviewDecision": effective_review_decision,
            "reviewForTaskId": review_for_task_id,
            "reviewForRunId": review_for_run_id,
            "reviewKind": review_kind,
            "dryRun": bool(dry_run),
            "codexThreadId": codex_thread_id,
            "configPath": str(config_path),
            "statusPath": str(status_path),
            "outputPath": str(output_path),
            "promptPath": str(prompt_path),
            "rawStreamPath": str(raw_stream_path),
            "tracePath": str(trace_path),
        }
        for candidate in workflow["tasks"].values():
            if isinstance(candidate, dict) and candidate.get("role") == "implementer":
                candidate["reviewDecision"] = implementer_review_decision(candidate)
        update_workflow_acceptance(workflow)
        write_json(path, workflow)
        return path
    finally:
        lock.release()


def record_agent_spawn(
    artifact_root: Path,
    workflow_id: str,
    task_id: str,
    agent_id: str,
) -> Path:
    path = workflow_path(artifact_root, workflow_id)
    lock = acquire_file_lock(
        workflow_lock_path(artifact_root, workflow_id),
        timeout_seconds=30,
        poll_seconds=0.05,
        message=lambda: f"Timed out waiting to record agent spawn: {path}",
    )
    try:
        workflow = load_json(path) if path.exists() else empty_workflow(workflow_id)
        attempts = workflow.setdefault("agentAttempts", {})
        existing = attempts.get(agent_id)
        if isinstance(existing, dict) and existing.get("taskId") not in (None, task_id):
            raise DelegateError(f"agent {agent_id} is already bound to task {existing.get('taskId')}")
        if isinstance(existing, dict) and existing.get("closeStatus") == "closed":
            raise DelegateError(f"agent {agent_id} is already closed and cannot be reused for another spawn attempt")
        attempt = existing if isinstance(existing, dict) else {}
        attempt.update(
            {
                "agentId": agent_id,
                "taskId": task_id,
                "spawnedAt": attempt.get("spawnedAt") or now_iso(),
                "spawnRecordedAt": attempt.get("spawnRecordedAt") or now_iso(),
                "closeStatus": attempt.get("closeStatus"),
            }
        )
        attempts[agent_id] = attempt
        workflow["revision"] = int(workflow.get("revision") or 0) + 1
        update_workflow_acceptance(workflow)
        write_json(path, workflow)
        return path
    finally:
        lock.release()


def record_agent_close(
    artifact_root: Path,
    workflow_id: str,
    task_id: str,
    agent_id: str,
) -> Path:
    path = workflow_path(artifact_root, workflow_id)
    lock = acquire_file_lock(
        workflow_lock_path(artifact_root, workflow_id),
        timeout_seconds=30,
        poll_seconds=0.05,
        message=lambda: f"Timed out waiting to record agent closure: {path}",
    )
    try:
        if not path.exists():
            raise DelegateError(f"workflow artifact does not exist: {path}")
        workflow = load_json(path)
        attempts = workflow.get("agentAttempts") if isinstance(workflow.get("agentAttempts"), dict) else {}
        attempt = attempts.get(agent_id)
        if not isinstance(attempt, dict):
            raise DelegateError(f"agent {agent_id} has no recorded spawn attempt")
        if attempt.get("taskId") != task_id:
            raise DelegateError(f"agent {agent_id} belongs to task {attempt.get('taskId')}, not {task_id}")
        if not attempt.get("spawnRecordedAt"):
            raise DelegateError(f"agent {agent_id} has no explicit spawn record")
        if not attempt.get("runId") or not attempt.get("runRecordedAt"):
            raise DelegateError(f"agent {agent_id} cannot be closed before its run is recorded")
        attempt["closeStatus"] = "closed"
        attempt["closedAt"] = now_iso()
        workflow["revision"] = int(workflow.get("revision") or 0) + 1
        update_workflow_acceptance(workflow)
        write_json(path, workflow)
        return path
    finally:
        lock.release()
