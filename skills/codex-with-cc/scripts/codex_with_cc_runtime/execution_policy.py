"""Explicit, immutable policy for new workflows. Missing policy means legacy strict."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .common import DelegateError, now_iso, same_path
from .io_utils import load_json, write_json
from .locks import acquire_file_lock


def profile(workflow: dict) -> str:
    policy = workflow.get("executionPolicy")
    if not policy:
        return "strict"
    if policy.get("schemaVersion") != 1 or policy.get("profile") not in ("standard", "strict"):
        raise DelegateError("Unsupported execution policy")
    return policy["profile"]


def configure(ns) -> int:
    from .artifacts import resolve_artifact_root
    from .workflow import empty_workflow, workflow_path, workflow_lock_path, update_workflow_acceptance
    root = resolve_artifact_root(ns.artifact_root, workflow_id=ns.workflow_id)
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", ns.workflow_id):
        raise DelegateError("WorkflowId must contain only letters, digits, underscores, dots and hyphens")
    if any(not str(value).strip() for value in (ns.carrier_model, ns.worker_model, ns.native_model)):
        raise DelegateError("Model settings cannot be empty")
    if any(value not in ("low", "medium", "high", "xhigh", "max", "ultra") for value in (ns.carrier_effort, ns.native_effort)):
        raise DelegateError("Unsupported reasoning effort")
    project = Path(ns.project_root).resolve()
    if not project.is_dir():
        raise DelegateError("Project root must be an existing directory")
    if project.is_relative_to(root):
        raise DelegateError("Artifact root must not contain or equal the project root")
    policy = {"schemaVersion": 1, "profile": ns.profile, "projectRoot": str(project),
              "carrierModel": ns.carrier_model, "carrierEffort": ns.carrier_effort,
              "workerModel": ns.worker_model, "nativeModel": ns.native_model, "nativeEffort": ns.native_effort}
    if getattr(ns, "max_parallel", None) is not None:
        from .adaptive import normalize_scopes
        policy["dispatch"] = {"schemaVersion": 1, "maxParallel": ns.max_parallel,
                              "mainScopes": normalize_scopes(project, ns.main_scope)}
    elif getattr(ns, "main_scope", None):
        raise DelegateError("MainScope requires MaxParallel to enable dispatch admission")
    lock = acquire_file_lock(workflow_lock_path(root, ns.workflow_id), 30, .05, lambda: "Workflow policy is locked")
    try:
        path = workflow_path(root, ns.workflow_id)
        w = load_json(path) if path.exists() else empty_workflow(ns.workflow_id)
        old = w.get("executionPolicy")
        if old and all(old.get(k) == v for k, v in policy.items()):
            print(path)
            return 0
        if w.get("runs") or w.get("tasks") or w.get("agentAttempts") or w.get("preparedTasks"):
            raise DelegateError("Execution policy is frozen after preparation or dispatch; create a new workflow")
        w["executionPolicy"] = {**policy, "configuredAt": now_iso()}
        from .metrics import capture_baseline
        w["mainUsageBaseline"] = capture_baseline()
        update_workflow_acceptance(w)
        write_json(path, w)
    finally:
        lock.release()
    print(path)
    return 0


def verify_project(workflow: dict, records: dict) -> None:
    roots = {str(Path(r["config"]["repoRoot"]).resolve()) for r in records.values() if r["config"].get("repoRoot")}
    expected = (workflow.get("executionPolicy") or {}).get("projectRoot")
    if len(roots) > 1:
        raise DelegateError("Workflow mixes runs from different projects")
    if expected and (not roots or any(not same_path(expected, r) for r in roots)):
        raise DelegateError("Workflow project identity does not match execution records")
    if expected and any(r["config"].get("executionPolicy") != workflow["executionPolicy"] for r in records.values()):
        raise DelegateError("Execution policy does not match the policy pinned at dispatch")

    for record in records.values():
        config = record["config"]
        task = workflow.get("tasks", {}).get(config.get("taskId"), {})
        if config.get("preparedPlanId") and task.get("latestRunId") == config.get("runId"):
            from .routing import verified_plan
            from .adaptive import require_current_dependencies
            entry = workflow["preparedTasks"][config["preparedPlanId"]]
            plan, _ = verified_plan(Path(entry["path"]))
            require_current_dependencies(plan, workflow)


def main_review_current(workflow: dict) -> bool:
    if profile(workflow) != "standard":
        return False
    review = workflow.get("mainReview") or {}
    expected = {tid: task.get("latestRunId") for tid, task in workflow.get("tasks", {}).items()}
    concerns = any(t.get("lastReportStatus") == "DONE_WITH_CONCERNS" for t in workflow.get("tasks", {}).values())
    return bool(expected) and review.get("decision") == "accepted" and review.get("runs") == expected and (not concerns or bool(review.get("concernDecisions")))


def require_main_thread() -> str:
    import os
    if os.environ.get("CODEX_CLAUDE_CHILD_THREAD") == "1":
        raise DelegateError("Main-thread review cannot be recorded by a worker")
    thread = os.environ.get("CODEX_THREAD_ID")
    if not thread:
        raise DelegateError("CODEX_THREAD_ID is required to attribute main-thread review")
    # Host provenance is additionally checked against recorded worker IDs by review recording.
    return thread
