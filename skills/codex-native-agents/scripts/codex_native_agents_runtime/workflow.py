from __future__ import annotations

import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from .common import ContractError
from .contract import load_contract
from .reports import parse_worker_report
from .routing import route_for_task
from .scope import normalize_scopes, scopes_overlap
from .task_contract import validate_task_file


if os.name == "nt":
    import msvcrt
else:
    import fcntl


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


def _workflow_revision(workflow: dict[str, Any]) -> int:
    revision = workflow.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise WorkflowError("Workflow record has invalid revision")
    return revision


def _advance_revision(workflow: dict[str, Any]) -> int:
    revision = _workflow_revision(workflow) + 1
    workflow["revision"] = revision
    return revision


def _ensure_mutable(workflow: dict[str, Any]) -> None:
    if workflow.get("status") == "accepted":
        raise WorkflowError("Accepted workflows are immutable; start a new WorkflowId")


def _validate_started_at(started_at: str | None) -> str | None:
    if started_at is None:
        return None
    try:
        parsed = datetime.fromisoformat(started_at.removesuffix("Z") + "+00:00" if started_at.endswith("Z") else started_at)
    except ValueError as error:
        raise WorkflowError("startedAt must be a timezone-aware ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise WorkflowError("startedAt must be a timezone-aware ISO-8601 timestamp")
    return started_at


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
        "revision": 0,
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
    _ensure_mutable(workflow)
    _workflow_revision(workflow)
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
        "spawnAttempts": [],
        "latestSpawn": None,
        "reviewForTaskId": review_for_task_id,
        "reviewKind": review_kind,
        "lastRunId": None,
        "latestRunId": None,
        "latestReportStatus": None,
        "latestReportFinalResult": None,
        "latestClose": None,
    }
    if role == "implementer":
        task["reviews"] = {kind: None for kind in contract["reviewKinds"]}
    if role == "final-verifier":
        task["lastAcceptanceSnapshot"] = None
    _advance_revision(workflow)
    tasks[task_id] = task
    return task


def record_spawn(
    workflow: dict[str, Any],
    *,
    task_id: str,
    agent_id: str,
    actual_model: str | None = None,
    inherit_parent: bool = False,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    _workflow_id(workflow)
    _ensure_mutable(workflow)
    _workflow_revision(workflow)
    task_id = _require_identifier(task_id, "Task")
    if not agent_id.strip():
        raise WorkflowError("Agent ID is required")
    if actual_model is None and not inherit_parent:
        raise WorkflowError("Spawn evidence requires an actual model or inherit_parent")
    if actual_model is not None and not actual_model.strip():
        raise WorkflowError("Actual model must not be empty")
    if inherit_parent and actual_model is not None:
        raise WorkflowError("Inherited execution cannot also declare an actual model")
    if fallback_reason is not None and not fallback_reason.strip():
        raise WorkflowError("Fallback reason must not be empty")

    task = _workflow_tasks(workflow).get(task_id)
    if task is None:
        raise WorkflowError(f"Unknown task: {task_id}")
    if inherit_parent and fallback_reason is None:
        raise WorkflowError("Inherited execution requires a fallback reason")
    if actual_model != task["requestedModel"] and fallback_reason is None:
        raise WorkflowError("Changed actual model requires a fallback reason")
    recorded_at = _now()
    spawn = {
        "agentId": agent_id,
        "requestedProfile": task["modelProfile"],
        "requestedModel": task["requestedModel"],
        "requestedReasoningEffort": task["reasoningEffort"],
        "actualModel": None if inherit_parent else actual_model,
        "executionMode": "inherit_parent" if inherit_parent else "model",
        "fallbackReason": fallback_reason,
        "recordedAt": recorded_at,
        "recordedRevision": _advance_revision(workflow),
    }
    task["spawnAttempts"].append(spawn)
    task["latestSpawn"] = spawn
    return spawn


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
    _ensure_mutable(workflow)
    _workflow_revision(workflow)
    task_id = _require_identifier(task_id, "Task")
    tasks = _workflow_tasks(workflow)
    task = tasks.get(task_id)
    if task is None:
        raise WorkflowError(f"Unknown task: {task_id}")
    spawn = task["latestSpawn"]
    if spawn is None:
        raise WorkflowError("Record run requires spawn evidence")
    if spawn["agentId"] != agent_id:
        raise WorkflowError("Record run agent ID must match latest spawn evidence")
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

    validated_started_at = _validate_started_at(started_at)
    if task["role"] == "reviewer":
        reviewed_task = tasks[task["reviewForTaskId"]]
        if reviewed_task["lastRunId"] is None:
            raise WorkflowError("Reviewer requires a recorded implementer run")

    recorded_at = _now()
    recorded_revision = _advance_revision(workflow)
    run = {
        "runId": run_id,
        "agentId": agent_id,
        "taskId": task_id,
        "modelProfile": task["modelProfile"],
        "requestedModel": task["requestedModel"],
        "reasoningEffort": task["reasoningEffort"],
        "fallback": task["fallback"],
        "spawn": spawn,
        "reportStatus": parsed_report.status,
        "reportFinalResult": parsed_report.final_result,
        "reportPath": report_path,
        "startedAt": validated_started_at or recorded_at,
        "recordedAt": recorded_at,
        "recordedRevision": recorded_revision,
    }
    decision = "accepted" if parsed_report.status == "DONE" else "rejected"
    if task["role"] in {"reviewer", "final-verifier"}:
        run["reviewDecision"] = decision
    runs[run_id] = run
    task["lastRunId"] = run_id
    task["latestRunId"] = run_id
    task["latestReportStatus"] = parsed_report.status
    task["latestReportFinalResult"] = parsed_report.final_result
    task["latestClose"] = None

    if task["role"] == "reviewer":
        reviewed_task["reviews"][task["reviewKind"]] = {
            "decision": decision,
            "reviewerTaskId": task_id,
            "reviewerRunId": run_id,
            "reviewedRunId": reviewed_task["lastRunId"],
            "reviewKind": task["reviewKind"],
            "recordedAt": recorded_at,
            "recordedRevision": recorded_revision,
        }
    if task["role"] == "final-verifier":
        snapshot = _acceptance_snapshot(tasks) if decision == "accepted" else None
        run["acceptanceSnapshot"] = snapshot
        task["lastAcceptanceSnapshot"] = snapshot
    return run


def record_close(
    workflow: dict[str, Any],
    *,
    task_id: str,
    agent_id: str,
    status: str,
) -> dict[str, Any]:
    _workflow_id(workflow)
    _ensure_mutable(workflow)
    _workflow_revision(workflow)
    task_id = _require_identifier(task_id, "Task")
    if not agent_id.strip():
        raise WorkflowError("Agent ID is required")
    if status != "closed":
        raise WorkflowError("Close status must be closed")

    task = _workflow_tasks(workflow).get(task_id)
    if task is None:
        raise WorkflowError(f"Unknown task: {task_id}")
    spawn = task.get("latestSpawn")
    run_id = task.get("latestRunId")
    if not isinstance(spawn, dict) or run_id is None:
        raise WorkflowError("Record close requires current spawn and run evidence")
    run = _workflow_runs(workflow).get(run_id)
    if run is None:
        raise WorkflowError("Record close requires the latest recorded run")
    if task.get("lastRunId") != run_id or run.get("spawn") != spawn:
        raise WorkflowError("Record close requires a run matching the latest spawn evidence")
    if agent_id != spawn.get("agentId") or agent_id != run.get("agentId"):
        raise WorkflowError("Record close agent ID must match the latest spawn and run")
    if run.get("closure") is not None:
        raise WorkflowError("Latest run already has close evidence")

    closure = {
        "agentId": agent_id,
        "runId": run_id,
        "reportStatus": run.get("reportStatus"),
        "status": status,
        "closedAt": _now(),
        "closedRevision": _advance_revision(workflow),
    }
    run["closure"] = closure
    task["latestClose"] = closure
    return closure


def _acceptance_snapshot(tasks: dict[str, dict[str, Any]]) -> list[dict[str, str | None]]:
    snapshot: list[dict[str, str | None]] = []
    for task_id, task in sorted(tasks.items()):
        if task["role"] != "implementer":
            continue
        reviews = task["reviews"]
        snapshot.append(
            {
                "implementerTaskId": task_id,
                "implementerRunId": task["lastRunId"],
                "specReviewerRunId": reviews["spec"]["reviewerRunId"] if reviews["spec"] and reviews["spec"]["decision"] == "accepted" else None,
                "qualityReviewerRunId": reviews["quality"]["reviewerRunId"] if reviews["quality"] and reviews["quality"]["decision"] == "accepted" else None,
            }
        )
    return snapshot


def _validate_workflow_structure(workflow: dict[str, Any]) -> None:
    contract = load_contract()
    _workflow_id(workflow)
    if workflow.get("artifactSchema") != contract["artifactSchemaVersion"]:
        raise WorkflowError("Workflow record has incompatible artifact schema")
    if workflow.get("invocationContract") != contract["invocationContract"]:
        raise WorkflowError("Workflow record has incompatible invocation contract")
    if workflow.get("status") not in {"running", "accepted"}:
        raise WorkflowError("Workflow record has invalid status")
    _workflow_revision(workflow)
    tasks = _workflow_tasks(workflow)
    runs = _workflow_runs(workflow)
    for task_id, task in tasks.items():
        if not isinstance(task, dict) or task.get("taskId") != task_id:
            raise WorkflowError("Workflow record has inconsistent task identity")
        if not isinstance(task.get("spawnAttempts"), list):
            raise WorkflowError(f"Task has invalid spawn evidence: {task_id}")
        if "latestClose" not in task:
            raise WorkflowError(f"Task has invalid close evidence: {task_id}")
    for run_id, run in runs.items():
        if not isinstance(run, dict) or run.get("runId") != run_id:
            raise WorkflowError("Workflow record has inconsistent run identity")
        if run.get("taskId") not in tasks:
            raise WorkflowError(f"Run references an unknown task: {run_id}")


def _accepted_run_for_task(task: dict[str, Any], runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    task_id = task["taskId"]
    if task.get("latestReportStatus") != "DONE":
        raise WorkflowError(f"Registered task is not DONE: {task_id}")
    run_id = task.get("latestRunId")
    if run_id is None or task.get("lastRunId") != run_id:
        raise WorkflowError(f"Registered task has no current recorded run: {task_id}")
    run = runs.get(run_id)
    if run is None or run.get("taskId") != task_id or run.get("reportStatus") != "DONE":
        raise WorkflowError(f"Registered task has invalid DONE run evidence: {task_id}")
    spawn = task.get("latestSpawn")
    if not isinstance(spawn, dict) or run.get("spawn") != spawn or run.get("agentId") != spawn.get("agentId"):
        raise WorkflowError(f"Registered task run must match latest spawn evidence: {task_id}")
    closure = task.get("latestClose")
    if not isinstance(closure, dict) or closure.get("status") != "closed":
        raise WorkflowError(f"Registered task is not closed: {task_id}")
    if (
        closure.get("runId") != run_id
        or closure.get("agentId") != run.get("agentId")
        or closure.get("reportStatus") != run.get("reportStatus")
        or run.get("closure") != closure
    ):
        raise WorkflowError(f"Registered task close evidence does not match the current run: {task_id}")
    return run


def _spawn_evidence_snapshot(tasks: dict[str, dict[str, Any]], runs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "taskId": task_id,
            "runId": task["latestRunId"],
            "spawn": runs[task["latestRunId"]]["spawn"],
        }
        for task_id, task in sorted(tasks.items())
    ]


def _closure_snapshot(tasks: dict[str, dict[str, Any]], runs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "taskId": task_id,
            "runId": task["latestRunId"],
            "agentId": runs[task["latestRunId"]]["agentId"],
            "reportStatus": runs[task["latestRunId"]]["reportStatus"],
            "closure": runs[task["latestRunId"]]["closure"],
        }
        for task_id, task in sorted(tasks.items())
    ]


def _validate_final_acceptance(
    workflow: dict[str, Any],
    *,
    implementers: list[dict[str, Any]],
    spawn_evidence: list[dict[str, Any]],
    closure_snapshot: list[dict[str, Any]],
) -> None:
    acceptance = workflow.get("finalAcceptance")
    if not isinstance(acceptance, dict) or acceptance.get("status") != "accepted":
        raise WorkflowError("Accepted workflow is missing final acceptance evidence")
    if acceptance.get("acceptedRevision") != workflow.get("revision"):
        raise WorkflowError("Accepted workflow has invalid acceptance revision")
    if acceptance.get("implementerTaskIds") != [task["taskId"] for task in implementers]:
        raise WorkflowError("Accepted workflow has invalid implementer task evidence")
    if acceptance.get("spawnEvidence") != spawn_evidence:
        raise WorkflowError("Accepted workflow has invalid spawn evidence")
    if acceptance.get("closureSnapshot") != closure_snapshot:
        raise WorkflowError("Accepted workflow has invalid closure snapshot")


def verify_workflow(workflow: dict[str, Any]) -> dict[str, Any]:
    _validate_workflow_structure(workflow)
    tasks = _workflow_tasks(workflow)
    runs = _workflow_runs(workflow)
    implementers = [task for task in tasks.values() if task["role"] == "implementer"]
    for task in implementers:
        if task["latestReportStatus"] != "DONE":
            raise WorkflowError(f"Implementer task is not DONE: {task['taskId']}")
        implementer_run = runs.get(task["lastRunId"])
        if implementer_run is None:
            raise WorkflowError(f"Implementer task has no recorded run: {task['taskId']}")
        for review_kind in load_contract()["reviewKinds"]:
            review = task["reviews"][review_kind]
            if review is None or review["decision"] != "accepted":
                raise WorkflowError(f"Implementer task requires accepted {review_kind} review: {task['taskId']}")
            reviewer_run = runs.get(review["reviewerRunId"])
            if review["reviewedRunId"] != task["lastRunId"]:
                raise WorkflowError(f"Accepted {review_kind} review must reference the current implementer run")
            if reviewer_run is None or reviewer_run["recordedRevision"] <= implementer_run["recordedRevision"]:
                raise WorkflowError(f"Accepted {review_kind} review must follow the implementer run")

    snapshots = _acceptance_snapshot(tasks)
    final_verifiers = [
        task
        for task in tasks.values()
        if task["role"] == "final-verifier" and task["latestReportStatus"] == "DONE"
    ]
    if implementers and not final_verifiers:
        raise WorkflowError("Implementer workflow requires an accepted DONE final verifier")
    if implementers:
        final_task = final_verifiers[-1]
        final_run = runs.get(final_task["lastRunId"])
        if final_run is None or final_run.get("reviewDecision") != "accepted":
            raise WorkflowError("Implementer workflow requires an accepted DONE final verifier")
        if final_run.get("acceptanceSnapshot") != snapshots or final_task.get("lastAcceptanceSnapshot") != snapshots:
            raise WorkflowError("final verifier snapshot is stale")
        for snapshot in snapshots:
            for review_run_id in (snapshot["specReviewerRunId"], snapshot["qualityReviewerRunId"]):
                reviewer_run = runs.get(review_run_id)
                if reviewer_run is None or final_run["recordedRevision"] <= reviewer_run["recordedRevision"]:
                    raise WorkflowError("final verifier must follow all accepted reviews")

    for task in tasks.values():
        _accepted_run_for_task(task, runs)
    spawn_evidence = _spawn_evidence_snapshot(tasks, runs)
    closure_snapshot = _closure_snapshot(tasks, runs)
    if workflow["status"] == "accepted":
        _validate_final_acceptance(
            workflow,
            implementers=implementers,
            spawn_evidence=spawn_evidence,
            closure_snapshot=closure_snapshot,
        )
        return workflow

    accepted_at = _now()
    acceptance_revision = _advance_revision(workflow)
    workflow["status"] = "accepted"
    workflow["finalAcceptance"] = {
        "status": "accepted",
        "acceptedAt": accepted_at,
        "acceptedRevision": acceptance_revision,
        "implementerTaskIds": [task["taskId"] for task in implementers],
        "spawnEvidence": spawn_evidence,
        "closureSnapshot": closure_snapshot,
    }
    return workflow


def workflow_path(artifact_root: Path, workflow_id: str) -> Path:
    workflow_id = _require_identifier(workflow_id, "Workflow")
    return artifact_root / f"workflow_{workflow_id}.json"


@contextmanager
def workflow_lock(
    artifact_root: Path,
    workflow_id: str,
    timeout_seconds: float = 5.0,
    retry_seconds: float = 0.05,
) -> Iterator[None]:
    path = workflow_path(artifact_root, workflow_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    deadline = time.monotonic() + timeout_seconds
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        while True:
            try:
                if os.name == "nt":
                    # msvcrt locks a byte range. Keep byte zero stable and retain this fd
                    # for the whole context; closing it releases the lock after a crash.
                    if os.fstat(descriptor).st_size == 0:
                        os.write(descriptor, b"\0")
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    # flock is process-owned kernel state on POSIX, so SIGKILL releases it.
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise WorkflowError(f"Timed out acquiring workflow lock: {workflow_id}")
                time.sleep(retry_seconds)
            else:
                acquired = True
                break
        yield
    finally:
        if acquired and os.name == "nt":
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        os.close(descriptor)


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
    "record_close",
    "record_run",
    "record_spawn",
    "register_task",
    "verify_workflow",
    "workflow_lock",
    "workflow_path",
    "write_workflow",
]
