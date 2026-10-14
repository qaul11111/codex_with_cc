"""Prepare reviewable task descriptors with separate host and execution models."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from .common import DelegateError, now_iso
from .io_utils import load_json, write_json
from .lifecycle import digest, require_lifecycle_preflight
from .locks import acquire_file_lock
from .task_contract import validate_task_file_contract


def run_prepare_task(ns) -> int:
    from .artifacts import resolve_artifact_root
    from .workflow import workflow_path, workflow_lock_path, safe_task_id
    from .adaptive import normalize_scopes
    from .claude_cli import role_effort
    root = resolve_artifact_root(ns.artifact_root, workflow_id=ns.workflow_id)
    if safe_task_id(ns.task_id) != ns.task_id or ns.task_id in (".", ".."):
        raise DelegateError("TaskId must be a stable filename-safe identifier")
    require_lifecycle_preflight(root, ns.workflow_id)
    text = Path(ns.task_file).read_text()
    validate_task_file_contract(text)
    if not ns.scope:
        raise DelegateError("Prepared tasks require an explicit scope")
    if ns.role == "reviewer" and not all((ns.review_for_task_id, ns.review_for_run_id, ns.review_kind)):
        raise DelegateError("Reviewer plans require exact target task/run and review kind")
    lock = acquire_file_lock(workflow_lock_path(root, ns.workflow_id), 30, .05, lambda: "Task preparation is locked")
    try:
        path = workflow_path(root, ns.workflow_id)
        w = load_json(path)
        policy = w.get("executionPolicy")
        if not policy:
            raise DelegateError("configure-workflow is required for explicit model routing")
        if getattr(ns, "admit", False) and not policy.get("dispatch"):
            raise DelegateError("prepare-task -Admit requires MaxParallel on a new workflow")
        project = Path(policy["projectRoot"])
        if ns.backend in ("claude-code", "claude-process") and not root.is_relative_to(project):
            raise DelegateError("Prepared Claude tasks require ArtifactRoot inside the project")
        scope = normalize_scopes(project, ns.scope)
        reads = normalize_scopes(project, ns.read_scope)
        if ns.task_id in ns.depends_on or any(d not in w.get("tasks", {}) and not any(x["taskId"] == d for x in w.get("preparedTasks", {}).values()) for d in ns.depends_on):
            raise DelegateError("Dependencies must name previously registered tasks and cannot include self")
        overrides = {k: getattr(ns, k) for k in ("carrier_model", "carrier_effort", "native_model", "native_effort", "worker_model", "worker_effort") if getattr(ns, k) is not None}
        unused = ({"carrier_model", "carrier_effort", "worker_model", "worker_effort"} if ns.backend == "codex-native"
                  else {"native_model", "native_effort"})
        if ns.backend == "claude-process":
            unused |= {"carrier_model", "carrier_effort"}
        if unused.intersection(overrides):
            raise DelegateError("Model/effort override does not apply to the selected backend")
        if (overrides or ns.inputs_complete) and not (ns.decision_reason or "").strip():
            raise DelegateError("Task overrides or complete-input declaration require DecisionReason")
        if any(not str(v).strip() for v in overrides.values()):
            raise DelegateError("Model overrides cannot be empty")
        if ns.max_budget_usd is not None:
            import math
            try:
                valid_budget = math.isfinite(float(ns.max_budget_usd)) and float(ns.max_budget_usd) > 0
            except ValueError:
                valid_budget = False
            if not valid_budget or ns.backend not in ("claude-code", "claude-process"):
                raise DelegateError("MaxBudgetUsd requires a positive finite Claude budget")
        plan_id = uuid.uuid4().hex
        directory = root / "plans" / safe_task_id(ns.task_id) / plan_id
        directory.mkdir(parents=True)
        task_file = directory / "task.md"
        task_file.write_text(text)
        native = ns.backend == "codex-native"
        plan = {"schemaVersion": 1, "planId": plan_id, "workflowId": ns.workflow_id,
                "taskId": ns.task_id, "role": ns.role, "backend": ns.backend,
                "artifactRoot": str(root), "projectRoot": str(project), "executionPolicy": policy,
                "taskFile": str(task_file), "taskSha256": digest(task_file), "scope": scope,
                "readScope": reads, "inputsComplete": ns.inputs_complete, "dependsOn": ns.depends_on,
                "hostEffortRequired": bool(ns.native_effort if ns.backend == "codex-native" else ns.carrier_effort),
                "complexity": ns.complexity, "decisionReason": ns.decision_reason, "maxBudgetUsd": ns.max_budget_usd,
                "workerEffort": None if native else (ns.worker_effort or role_effort(ns.role)),
                "tests": ns.tests, "allowParallel": ns.allow_parallel, "createdAt": now_iso(),
                "model": (ns.native_model if native else ns.carrier_model) or policy["nativeModel" if native else "carrierModel"],
                "reasoningEffort": (ns.native_effort if native else ns.carrier_effort) or policy["nativeEffort" if native else "carrierEffort"],
                "workerModel": None if native else (ns.worker_model or policy["workerModel"]),
                "reviewForTaskId": ns.review_for_task_id, "reviewForRunId": ns.review_for_run_id, "reviewKind": ns.review_kind}
        if ns.backend == "claude-process":
            from .process_run import prepare_process
            prepare_process(plan, ns)
        elif getattr(ns, "allowed_commands_file", None):
            raise DelegateError("AllowedCommandsFile requires claude-process")
        elif getattr(ns, "execution_timeout_seconds", None) is not None:
            raise DelegateError("Prepared ExecutionTimeoutSeconds requires claude-process")
        if ns.role == "final-verifier":
            from .workflow import final_verifier_snapshot
            plan["verifiedImplementerRuns"] = final_verifier_snapshot(w)
        plan_path = directory / "plan.json"
        write_json(plan_path, plan)
        if ns.backend == "claude-process":
            launch = {"version": "1.2.0", "invocation": "codex_with_cc_process",
                      "mainThread": {"threadId": plan["mainHost"]["threadId"]},
                      "projectWorkingDirectory": str(project), "taskFile": str(task_file.relative_to(project)),
                      "workflowId": ns.workflow_id, "taskId": ns.task_id, "role": ns.role, "artifactRoot": str(root)}
            (directory / "launch.json").write_text(json.dumps(launch, indent=2))
            plan["launchTemplate"] = launch
            write_json(plan_path, plan)
        elif not native:
            launch = {"version": "1.2.0", "invocation": "codex_with_cc_workflow",
                      "childThread": {"threadId": "unbound-prepared-task"},
                      "projectWorkingDirectory": str(project), "taskFile": str(task_file.relative_to(project)),
                      "workflowId": ns.workflow_id, "taskId": ns.task_id, "role": ns.role,
                      "sessionKey": ns.session_key or ns.workflow_id, "scope": scope, "tests": ns.tests,
                      "dependsOn": ns.depends_on, "workerEffort": plan["workerEffort"],
                      "artifactRoot": str(root), "model": plan["workerModel"], "bypassPermissions": ns.bypass_permissions,
                      "session": {"sessionMode": "ParallelPool" if ns.allow_parallel or ns.role in ("reviewer", "final-verifier") else "PrimaryReuse", "allowParallel": ns.allow_parallel}}
            if ns.max_budget_usd is not None:
                launch["maxBudgetUsd"] = ns.max_budget_usd
            if ns.role == "reviewer":
                launch["review"] = {"reviewForTaskId": ns.review_for_task_id, "reviewForRunId": ns.review_for_run_id, "reviewKind": ns.review_kind}
            # The fixed launcher does not accept updatedAt, unlike workflow JSON.
            (directory / "launch.json").write_text(json.dumps(launch, indent=2))
            plan["launchTemplate"] = launch
            write_json(plan_path, plan)
        w.setdefault("preparedTasks", {})[plan_id] = {"path": str(plan_path), "sha256": digest(plan_path), "taskId": ns.task_id}
        from .workflow import update_workflow_acceptance
        update_workflow_acceptance(w)
        write_json(path, w)
    finally:
        lock.release()
    if getattr(ns, "admit", False):
        from argparse import Namespace
        from .adaptive import run_admit
        try:
            return run_admit(Namespace(plan_file=str(plan_path)))
        except DelegateError as exc:
            raise DelegateError(f"Plan remains queued at {plan_path}; admission failed: {exc}") from exc
    if policy.get("dispatch"):
        print(json.dumps({"planFile": str(plan_path), "status": "queued", "next": "ready-tasks then admit-task; preparation alone does not authorize spawn"}))
    else:
        print(json.dumps(spawn_payload(plan_path, plan), indent=2))
    return 0


def spawn_payload(plan_path: Path, plan: dict) -> dict:
    if plan["backend"] == "claude-process":
        from .fixed_launcher import _resolve_codex_home
        return {"planFile": str(plan_path), "backend": "claude-process", "launch": {
            "cmd": str(_resolve_codex_home() / "bin/codex-with-cc-launch"), "workdir": str(plan_path.parent)},
            "executionTimeoutSeconds": plan["executionTimeoutSeconds"],
            "instruction": "Main invokes this literal no-argument fixed launcher. Do not create a carrier child."}
    instruction = f"WorkflowPlan: {plan_path}\nRead the prepared task at {plan['taskFile']}. "
    if plan["backend"] == "codex-native":
        instruction += "Execute it directly with Codex tools inside its allowed scope. Do not delegate further. Return the structured report required by the task. The main thread records your original terminal transcript."
    else:
        instruction += f"Act only as the carrier. Use the literal no-argument fixed launcher under CODEX_HOME/bin, with terminal working directory {plan_path.parent}. Relay only the compact result packet and its artifact paths; do not read or repeat the full report or logs unless asked. Do not perform the worker task yourself."
    return {"planFile": str(plan_path), "spawn": {"task_name": plan["taskId"].replace('-', '_') + '_' + plan["planId"][:8],
            "fork_turns": "none", "model": plan["model"], "reasoning_effort": plan["reasoningEffort"], "message": instruction}}


def verified_plan(path: Path, *, allow_cancelled: bool = False, allow_unadmitted: bool = False) -> tuple[dict, dict]:
    from .workflow import workflow_path
    p = load_json(path)
    w = load_json(workflow_path(p["artifactRoot"], p["workflowId"]))
    record = (w.get("preparedTasks") or {}).get(p.get("planId")) or {}
    if record.get("path") != str(path.resolve()) or record.get("sha256") != digest(path):
        raise DelegateError("Prepared task descriptor was changed or is unregistered")
    if p.get("executionPolicy") != w.get("executionPolicy") or digest(Path(p["taskFile"])) != p.get("taskSha256"):
        raise DelegateError("Prepared task policy or content changed")
    if not allow_cancelled and (record.get("status") == "cancelled" or record.get("cancellation")):
        raise DelegateError("Prepared task was cancelled; prepare a fresh plan before dispatch")
    if not allow_unadmitted and not allow_cancelled:
        from .adaptive import verify_admission
        verify_admission(p, w)
    return p, w
