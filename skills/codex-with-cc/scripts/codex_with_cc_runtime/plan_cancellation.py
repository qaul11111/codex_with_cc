"""Audited withdrawal of prepared plans that have not been dispatched.

Withdrawal is not execution success. Original plans and previous workflow bytes
are retained, and the dispatch/import paths reject a withdrawn plan.
"""
from __future__ import annotations

import json
from pathlib import Path
import uuid

from .common import DelegateError, now_iso
from .dispatch_evidence import original_records
from .host_evidence import session_metadata, verify_main_identity
from .io_utils import load_json, write_json
from .lifecycle import digest, sessions_root, timestamp
from .locks import acquire_file_lock


def cancelled(record: dict) -> bool:
    return record.get("status") == "cancelled"


def assert_no_execution(plan: dict, workflow: dict, *, before_cancellation: bool) -> None:
    entry = workflow["preparedTasks"][plan["planId"]]
    task_name = plan["taskId"].replace("-", "_") + "_" + plan["planId"][:8]
    if entry.get("runId") or (Path(entry["path"]).parent / "claimed").exists():
        raise DelegateError("Cannot cancel a plan with execution or launcher claim evidence")
    for attempt in (workflow.get("agentAttempts") or {}).values():
        if (attempt.get("preparedPlanId") == plan["planId"]
                or str(attempt.get("agentId", "")).endswith("/" + task_name)
                or (before_cancellation and attempt.get("taskId") == plan["taskId"])):
            raise DelegateError("Cannot cancel a dispatched task; settle its actual execution")
    if before_cancellation and any(r.get("taskId") == plan["taskId"] for r in workflow.get("runs", {}).values()):
        raise DelegateError("Cannot cancel a task with recorded runs")
    for path in Path(plan["artifactRoot"]).glob("config_*.json"):
        config = load_json(path)
        if (config.get("preparedPlanId") == plan["planId"]
                or (before_cancellation and config.get("workflowId") == plan["workflowId"]
                    and config.get("taskId") == plan["taskId"])):
            raise DelegateError("Cannot cancel a plan with existing runner artifacts")
    # Catch a real spawn even if the parent failed before record-agent-spawn.
    parent_id = (workflow.get("mainUsageBaseline") or {}).get("threadId")
    if parent_id:
        identity = verify_main_identity(parent_id, plan["projectRoot"])
        for record in original_records(Path(identity["path"])):
            p = record.get("payload") or {}
            if (record.get("type") != "response_item" or p.get("type") != "function_call"
                    or p.get("name") not in ("spawn_agent", "collaboration.spawn_agent")):
                continue
            try:
                args = json.loads(p.get("arguments", ""))
            except (TypeError, ValueError):
                continue
            if isinstance(args, dict) and (args.get("task_name") == task_name
                    or f"WorkflowPlan: {entry['path']}" in str(args.get("message", "")).splitlines()):
                raise DelegateError("Cannot cancel: original parent log already records dispatch")
    for path in sessions_root().rglob("*.jsonl"):
        # Only metadata is needed; never ingest another task's conversation body.
        meta = session_metadata(path)
        source = meta.get("source") or {}
        spawn = ((source.get("subagent") or {}).get("thread_spawn") or {}) if isinstance(source, dict) else {}
        if (meta.get("cwd") == plan["projectRoot"]
                and str(spawn.get("agent_path", "")).endswith("/" + task_name)):
            raise DelegateError("Cannot cancel: original host child already exists")


def verify_cancellation(root: Path, workflow: dict, plan_id: str) -> dict:
    from .routing import verified_plan
    record = workflow["preparedTasks"][plan_id]
    receipt_ref = record.get("cancellation") or {}
    path = Path(receipt_ref.get("path", ""))
    if (not cancelled(record) or not path.resolve().is_relative_to((root / "cancellations").resolve())
            or not path.is_file() or path.is_symlink() or digest(path) != receipt_ref.get("sha256")):
        raise DelegateError("Prepared cancellation is missing or changed")
    receipt = load_json(path)
    plan, _ = verified_plan(Path(record["path"]), allow_cancelled=True)
    expected = {"schemaVersion": 1, "status": "cancelled", "workflowId": workflow["workflowId"],
                "planId": plan_id, "taskId": plan["taskId"], "planPath": record["path"],
                "planSha256": record["sha256"], "taskSha256": plan["taskSha256"]}
    if any(receipt.get(k) != v for k, v in expected.items()) or not str(receipt.get("reason", "")).strip():
        raise DelegateError("Prepared cancellation identity or reason is invalid")
    if timestamp(receipt.get("cancelledAt")) < timestamp(plan["createdAt"]):
        raise DelegateError("Cancellation predates task preparation")
    actor = receipt.get("actor") or {}
    if verify_main_identity(actor.get("threadId", ""), actor.get("projectRoot", "")) != actor.get("identity"):
        raise DelegateError("Cancellation main-thread identity changed")
    backup = Path(receipt.get("backupPath", ""))
    if (not backup.resolve().is_relative_to((root / "cancellations").resolve()) or not backup.is_file()
            or backup.is_symlink() or digest(backup) != receipt.get("workflowBeforeSha256")):
        raise DelegateError("Cancellation audit backup is missing or changed")
    old = load_json(backup)
    previous = old.get("preparedTasks", {}).get(plan_id, {})
    if (old.get("workflowId") != workflow["workflowId"] or previous.get("sha256") != record["sha256"]
            or previous.get("path") != record["path"] or previous.get("runId") or cancelled(previous)):
        raise DelegateError("Cancellation backup does not contain the original unexecuted plan")
    assert_no_execution(plan, workflow, before_cancellation=False)
    return receipt


def verify_cancellations(root: Path, workflow: dict) -> None:
    for plan_id, record in workflow.get("preparedTasks", {}).items():
        if cancelled(record) or record.get("cancellation") is not None:
            verify_cancellation(root, workflow, plan_id)


def run_cancel_prepared_task(ns) -> int:
    from .execution_policy import require_main_thread
    from .routing import verified_plan
    from .workflow import workflow_path, workflow_lock_path, update_workflow_acceptance
    reason = ns.reason.strip()
    if not reason:
        raise DelegateError("Cancellation requires a non-empty reason")
    thread = require_main_thread()
    actor_project = str(Path.cwd().resolve())
    identity = verify_main_identity(thread, actor_project)
    plan_path = Path(ns.plan_file).resolve()
    plan, _ = verified_plan(plan_path, allow_cancelled=True)
    root = Path(plan["artifactRoot"])
    lock = acquire_file_lock(workflow_lock_path(root, plan["workflowId"]), 30, .05,
                             lambda: "Prepared task cancellation is locked")
    try:
        plan, workflow = verified_plan(plan_path, allow_cancelled=True)
        record = workflow["preparedTasks"][plan["planId"]]
        if cancelled(record):
            receipt = verify_cancellation(root, workflow, plan["planId"])
            if receipt["reason"] != reason:
                raise DelegateError("Plan is already cancelled; its original reason cannot be overwritten")
            print(json.dumps({"status": "already-cancelled", "receipt": record["cancellation"]["path"]}))
            return 0
        assert_no_execution(plan, workflow, before_cancellation=True)
        original = workflow_path(root, plan["workflowId"])
        audit_id = uuid.uuid4().hex
        directory = root / "cancellations"
        directory.mkdir(exist_ok=True)
        backup = directory / f"{audit_id}.before.json"
        with backup.open("xb") as handle:
            handle.write(original.read_bytes())
        receipt_path = directory / f"{audit_id}.json"
        receipt = {"schemaVersion": 1, "status": "cancelled", "workflowId": plan["workflowId"],
                   "planId": plan["planId"], "taskId": plan["taskId"], "planPath": str(plan_path),
                   "planSha256": digest(plan_path), "taskSha256": plan["taskSha256"],
                   "cancelledAt": now_iso(), "reason": reason, "backupPath": str(backup),
                   "workflowBeforeSha256": digest(backup),
                   "actor": {"threadId": thread, "projectRoot": actor_project, "identity": identity}}
        write_json(receipt_path, receipt)
        record.update(status="cancelled", cancellation={"path": str(receipt_path), "sha256": digest(receipt_path)})
        workflow["revision"] = int(workflow.get("revision") or 0) + 1
        update_workflow_acceptance(workflow)
        write_json(original, workflow)
    finally:
        lock.release()
    print(json.dumps({"status": "cancelled", "taskId": plan["taskId"], "planId": plan["planId"],
                      "receipt": str(receipt_path), "next": "Run verify-workflow; cancellation is not execution success."}))
    return 0
