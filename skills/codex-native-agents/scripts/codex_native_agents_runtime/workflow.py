from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .common import ContractError
from .contract import load_contract
from .reports import parse_worker_report
from .routing import route_for_task
from .scope import normalize_scopes, scopes_overlap
from .task_contract import validate_task_file


IDENTIFIER = re.compile(r"[A-Za-z0-9._-]+")


class WorkflowError(ValueError):
    """Raised when a workflow record cannot satisfy its contract."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_identifier(value: str, label: str) -> str:
    if not IDENTIFIER.fullmatch(value) or ".." in value:
        raise WorkflowError(f"{label} identifier is invalid")
    return value


def _workflow_id(workflow: dict[str, Any]) -> str:
    value = workflow.get("workflowId")
    if not isinstance(value, str):
        raise WorkflowError("Workflow record is missing workflowId")
    return _require_identifier(value, "Workflow")


def _workflow_tasks(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tasks = workflow.get("tasks")
    if not isinstance(tasks, dict):
        raise WorkflowError("Workflow record has invalid tasks")
    return tasks


def _workflow_runs(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    runs = workflow.get("runs")
    if not isinstance(runs, dict):
        raise WorkflowError("Workflow record has invalid runs")
    return runs


def _route(role: str, complexity: str) -> Any:
    try:
        return route_for_task(role, complexity)
    except KeyError as error:
        raise WorkflowError(f"Unsupported worker role: {role}") from error


def new_workflow(workflow_id: str) -> dict[str, Any]:
    workflow_id = _require_identifier(workflow_id, "Workflow")
    return {
        "artifactSchema": load_contract()["artifactSchemaVersion"],
        "invocationContract": load_contract()["invocationContract"],
        "workflowId": workflow_id,
        "status": "running",
        "tasks": {},
        "runs": {},
        "finalAcceptance": None,
    }


def register_task(
    workflow: dict[str, Any],
    *,
    task_id: str,
    role: str,
    scopes: Iterable[str],
    writable: bool,
    parallel: bool = False,
    task_file: Path | None = None,
    model_profile: str | None = None,
    complexity: str = "normal",
    review_for_task_id: str | None = None,
    review_kind: str | None = None,
) -> dict[str, Any]:
    _workflow_id(workflow)
    task_id = _require_identifier(task_id, "Task")
    tasks = _workflow_tasks(workflow)
    if task_id in tasks:
        raise WorkflowError(f"Task already registered: {task_id}")
    try:
        normalized_scopes = normalize_scopes(scopes)
    except ContractError as error:
        raise WorkflowError(str(error)) from error
    route = _route(role, complexity)
    if model_profile is not None and model_profile != route.profile:
        raise WorkflowError(f"Model profile must match routed profile: {route.profile}")

    if writable and parallel:
        for registered_task in tasks.values():
            if registered_task["writable"] and registered_task["parallel"] and scopes_overlap(
                normalized_scopes, registered_task["scopes"]
            ):
                raise WorkflowError("Parallel writable task scopes overlap")

    contract = load_contract()
    if role == "reviewer":
        if review_for_task_id is None or review_kind is None:
            raise WorkflowError("Reviewer tasks require review_for_task_id and review_kind")
        review_for_task_id = _require_identifier(review_for_task_id, "Review target task")
        reviewed_task = tasks.get(review_for_task_id)
        if reviewed_task is None or reviewed_task["role"] != "implementer":
            raise WorkflowError("Reviewer target must be a registered implementer task")
        if review_kind not in contract["reviewKinds"]:
            raise WorkflowError(f"Unsupported review kind: {review_kind}")
    elif review_for_task_id is not None or review_kind is not None:
        raise WorkflowError("Only reviewer tasks may declare review metadata")

    sections = None
    if task_file is not None:
        try:
            sections = validate_task_file(task_file, role)
        except ContractError as error:
            raise WorkflowError(str(error)) from error

    task = {
        "taskId": task_id,
        "role": role,
        "scopes": list(normalized_scopes),
        "writable": writable,
        "parallel": parallel,
        "taskFile": str(task_file) if task_file is not None else None,
        "taskSections": sections,
        "modelProfile": route.profile,
        "requestedModel": route.model,
        "reasoningEffort": route.reasoning_effort,
        "fallback": route.fallback,
        "reviewForTaskId": review_for_task_id,
        "reviewKind": review_kind,
        "latestRunId": None,
        "latestReportStatus": None,
        "latestReportFinalResult": None,
    }
    if role == "implementer":
        task["reviews"] = {kind: None for kind in contract["reviewKinds"]}
    tasks[task_id] = task
    return task


def record_run(
    workflow: dict[str, Any],
    *,
    task_id: str,
    agent_id: str,
    report: str,
    report_path: str | None = None,
    run_id: str | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    _workflow_id(workflow)
    task_id = _require_identifier(task_id, "Task")
    tasks = _workflow_tasks(workflow)
    task = tasks.get(task_id)
    if task is None:
        raise WorkflowError(f"Unknown task: {task_id}")
    runs = _workflow_runs(workflow)
    run_id = _require_identifier(run_id or f"run-{len(runs) + 1}", "Run")
    if run_id in runs:
        raise WorkflowError(f"Run already recorded: {run_id}")
    try:
        parsed_report = parse_worker_report(report)
    except ContractError as error:
        raise WorkflowError(str(error)) from error
    if parsed_report.role != task["role"]:
        raise WorkflowError("Report role must match the registered task role")

    recorded_at = _now()
    run = {
        "runId": run_id,
        "agentId": agent_id,
        "taskId": task_id,
        "modelProfile": task["modelProfile"],
        "requestedModel": task["requestedModel"],
        "reasoningEffort": task["reasoningEffort"],
        "fallback": task["fallback"],
        "reportStatus": parsed_report.status,
        "reportFinalResult": parsed_report.final_result,
        "reportPath": report_path,
        "startedAt": started_at or recorded_at,
        "recordedAt": recorded_at,
    }
    decision = "accepted" if parsed_report.status == "DONE" else "rejected"
    if task["role"] in {"reviewer", "final-verifier"}:
        run["reviewDecision"] = decision
    runs[run_id] = run
    task["latestRunId"] = run_id
    task["latestReportStatus"] = parsed_report.status
    task["latestReportFinalResult"] = parsed_report.final_result

    if task["role"] == "reviewer":
        reviewed_task = tasks[task["reviewForTaskId"]]
        reviewed_task["reviews"][task["reviewKind"]] = {
            "decision": decision,
            "reviewerTaskId": task_id,
            "reviewerRunId": run_id,
            "recordedAt": recorded_at,
        }
    return run


def verify_workflow(workflow: dict[str, Any]) -> dict[str, Any]:
    _workflow_id(workflow)
    tasks = _workflow_tasks(workflow)
    implementers = [task for task in tasks.values() if task["role"] == "implementer"]
    for task in implementers:
        if task["latestReportStatus"] != "DONE":
            raise WorkflowError(f"Implementer task is not DONE: {task['taskId']}")
        for review_kind in load_contract()["reviewKinds"]:
            review = task["reviews"][review_kind]
            if review is None or review["decision"] != "accepted":
                raise WorkflowError(f"Implementer task requires accepted {review_kind} review: {task['taskId']}")
    if implementers and not any(
        task["role"] == "final-verifier" and task["latestReportStatus"] == "DONE"
        for task in tasks.values()
    ):
        raise WorkflowError("Implementer workflow requires an accepted DONE final verifier")

    accepted_at = _now()
    workflow["status"] = "accepted"
    workflow["finalAcceptance"] = {
        "status": "accepted",
        "acceptedAt": accepted_at,
        "implementerTaskIds": [task["taskId"] for task in implementers],
    }
    return workflow


def workflow_path(artifact_root: Path, workflow_id: str) -> Path:
    workflow_id = _require_identifier(workflow_id, "Workflow")
    return artifact_root / f"workflow_{workflow_id}.json"


def write_workflow(artifact_root: Path, workflow: dict[str, Any]) -> Path:
    path = workflow_path(artifact_root, _workflow_id(workflow))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(workflow, temporary_file, indent=2, sort_keys=True)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return path


def load_workflow(artifact_root: Path, workflow_id: str) -> dict[str, Any]:
    path = workflow_path(artifact_root, workflow_id)
    try:
        with path.open(encoding="utf-8") as workflow_file:
            workflow = json.load(workflow_file)
    except FileNotFoundError as error:
        raise WorkflowError(f"Workflow does not exist: {workflow_id}") from error
    if not isinstance(workflow, dict):
        raise WorkflowError("Workflow record must be a JSON object")
    _workflow_id(workflow)
    return workflow


__all__ = [
    "WorkflowError",
    "load_workflow",
    "new_workflow",
    "record_run",
    "register_task",
    "verify_workflow",
    "workflow_path",
    "write_workflow",
]
