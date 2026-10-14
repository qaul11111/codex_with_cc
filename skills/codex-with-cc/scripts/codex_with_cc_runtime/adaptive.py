"""Main-owned routing advice and atomic admission, adapted from native-only.

Advice never starts a model. Admission reserves capacity before a host spawn,
including the uncertain interval before record-agent-spawn returns.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .common import DelegateError, now_iso
from .io_utils import load_json, write_json
from .lifecycle import digest
from .locks import acquire_file_lock


def normalize_scopes(project: Path, scopes: list[str]) -> list[str]:
    normalized = []
    project = project.resolve()
    for value in scopes:
        if not value.strip() or any(c in value for c in "*?[]\0"):
            raise DelegateError("Scopes must be literal project paths, not globs")
        p = Path(value)
        if p.is_absolute() or ".." in p.parts or not (project / p).resolve().is_relative_to(project):
            raise DelegateError("Scope must stay inside the project")
        target = project / p
        if target.is_symlink() or any(parent.is_symlink() for parent in target.parents if parent.is_relative_to(project)):
            raise DelegateError("Scope contains a symlink; declare the real project path")
        normalized.append(p.as_posix())
    return sorted(set(normalized))


def overlaps(left: list[str], right: list[str]) -> bool:
    return any(Path(a).is_relative_to(Path(b)) or Path(b).is_relative_to(Path(a)) for a in left for b in right)


def access(plan: dict) -> tuple[list[str], list[str]]:
    return (plan["scope"] if plan["role"] == "implementer" else [],
            sorted(set(plan["scope"] + plan.get("readScope", []))))


def conflict(a: dict, b: dict) -> bool:
    aw, ar = access(a); bw, br = access(b)
    return overlaps(aw, br) or overlaps(bw, ar)


def settled(attempt: dict) -> bool:
    return bool(attempt.get("settledAt") or attempt.get("closeStatus") == "closed")


def all_attempts(workflow: dict) -> list[dict]:
    return list(workflow.get("agentAttempts", {}).values()) + list(workflow.get("processAttempts", {}).values())


def occupied(workflow: dict, plan: dict) -> bool:
    entry = workflow["preparedTasks"][plan["planId"]]
    if entry.get("status") == "cancelled":
        return False
    matches = [a for a in all_attempts(workflow)
               if a.get("preparedPlanId") == plan["planId"] or (entry.get("runId") and a.get("runId") == entry["runId"])]
    if matches:
        return any(not settled(a) for a in matches)
    return bool(entry.get("admission") or entry.get("runId"))


def plans_for(workflow: dict) -> list[dict]:
    from .routing import verified_plan
    return [verified_plan(Path(e["path"]), allow_unadmitted=True)[0]
            for e in workflow.get("preparedTasks", {}).values() if e.get("status") != "cancelled"]


def blockers(workflow: dict, plan: dict, plans: list[dict], reserved: list[dict] | None = None) -> list[str]:
    policy = workflow["executionPolicy"]["dispatch"]
    for item in plans:
        normalize_scopes(Path(item["projectRoot"]), access(item)[1])
    active = [p for p in plans if p["planId"] != plan["planId"] and occupied(workflow, p)] + (reserved or [])
    problems = []
    # Unknown/legacy active attempts still consume capacity and have unknown scope.
    known_ids = {p["planId"] for p in plans}
    unknown = [a for a in all_attempts(workflow)
               if not settled(a) and a.get("preparedPlanId") not in known_ids]
    if unknown:
        problems.append("unbound active child")
    if len(active) + len(unknown) >= policy["maxParallel"]:
        problems.append("concurrency limit")
    for other in active:
        if other["taskId"] == plan["taskId"] or not plan["allowParallel"] or not other["allowParallel"] or conflict(plan, other):
            problems.append("active scope/serial task:" + other["taskId"])
    if overlaps(access(plan)[1], policy.get("mainScopes", [])):
        problems.append("main-thread reserved scope")
    dependencies = list(plan.get("dependsOn", []))
    if plan.get("reviewForTaskId"):
        dependencies.append(plan["reviewForTaskId"])
    for tid in dependencies:
        task = workflow.get("tasks", {}).get(tid, {})
        attempts = [a for a in all_attempts(workflow) if a.get("taskId") == tid]
        reviewed_concerns = False
        if task.get("lastReportStatus") == "DONE_WITH_CONCERNS":
            from .check_evidence import verify_main_review
            from .execution_policy import profile
            try:
                if profile(workflow) == "standard":
                    verify_main_review(Path(plan["artifactRoot"]), workflow)
                    reviewed_concerns = True
            except DelegateError:
                pass
        if (task.get("status") != "completed" or (task.get("lastReportStatus") != "DONE" and not reviewed_concerns)
                or not attempts or any(not settled(a) for a in attempts)
                or any(p["taskId"] == tid and not workflow["preparedTasks"][p["planId"]].get("runId") for p in plans)):
            problems.append("dependency:" + tid)
        if tid == plan.get("reviewForTaskId") and task.get("latestRunId") != plan.get("reviewForRunId"):
            problems.append("stale review target:" + tid)
    if plan["role"] == "final-verifier":
        from .workflow import final_verifier_snapshot
        from .execution_policy import profile
        snapshot = final_verifier_snapshot(workflow)
        if not snapshot or snapshot != plan.get("verifiedImplementerRuns"):
            problems.append("stale final-verifier inputs")
        if profile(workflow) == "strict" and any(t.get("reviewDecision") != "accepted" for t in workflow.get("tasks", {}).values() if t["role"] == "implementer"):
            problems.append("current independent reviews missing")
    return problems


def verify_admission(plan: dict, workflow: dict) -> None:
    if not workflow.get("executionPolicy", {}).get("dispatch"):
        return
    entry = workflow["preparedTasks"][plan["planId"]]
    ref = entry.get("admission") or {}
    path = Path(ref.get("path", ""))
    expected_path = Path(entry["path"]).parent / "admission.json"
    if path != expected_path or path.is_symlink() or not path.is_file() or digest(path) != ref.get("sha256"):
        raise DelegateError("Prepared task has no valid admission; run admit-task before spawning")
    record = load_json(path)
    if record.get("planId") != plan["planId"] or record.get("planSha256") != entry["sha256"]:
        raise DelegateError("Dispatch admission does not match the prepared task")
    expected = set(plan.get("dependsOn", [])) | ({plan["reviewForTaskId"]} if plan.get("reviewForTaskId") else set())
    deps = record.get("dependencyRuns", {})
    if set(deps) != expected or any(workflow.get("runs", {}).get(rid, {}).get("taskId") != tid for tid, rid in deps.items()):
        raise DelegateError("Dispatch dependency evidence is missing")


def require_current_dependencies(plan: dict, workflow: dict) -> None:
    if not workflow.get("executionPolicy", {}).get("dispatch"):
        return
    verify_admission(plan, workflow)
    ref = workflow["preparedTasks"][plan["planId"]]["admission"]
    dependencies = load_json(Path(ref["path"]))["dependencyRuns"]
    if any(workflow.get("tasks", {}).get(tid, {}).get("latestRunId") != rid for tid, rid in dependencies.items()):
        raise DelegateError("Dispatch dependency evidence is stale; prepare a fresh dependent attempt")


def run_ready(ns) -> int:
    from .workflow import workflow_path
    w = load_json(workflow_path(Path(ns.artifact_root), ns.workflow_id))
    if not w.get("executionPolicy", {}).get("dispatch"):
        raise DelegateError("Configure MaxParallel on a new workflow to use adaptive admission")
    plans = plans_for(w); ready = []; blocked = {}
    for p in plans:
        entry = w["preparedTasks"][p["planId"]]
        if entry.get("runId") or entry.get("admission"):
            continue
        reasons = blockers(w, p, plans, ready)
        if reasons:
            blocked[p["planId"]] = {"taskId": p["taskId"], "reasons": reasons}
        else:
            ready.append(p)
    print(json.dumps({"ready": [{"taskId": p["taskId"], "planFile": w["preparedTasks"][p["planId"]]["path"]} for p in ready],
                      "blocked": blocked, "next": "admit-task reserves each selected plan atomically; recompute after settlement"}))
    return 0


def run_admit(ns) -> int:
    from .routing import verified_plan, spawn_payload
    from .workflow import workflow_path, workflow_lock_path
    from .execution_policy import require_main_thread
    from .host_evidence import verify_main_identity
    actor = require_main_thread()
    identity = verify_main_identity(actor, str(Path.cwd().resolve()))
    path = Path(ns.plan_file).resolve()
    p, w = verified_plan(path, allow_unadmitted=True)
    root = Path(p["artifactRoot"])
    lock = acquire_file_lock(workflow_lock_path(root, p["workflowId"]), 30, .05, lambda: "Dispatch admission locked")
    try:
        p, w = verified_plan(path, allow_unadmitted=True)
        if not w["executionPolicy"].get("dispatch"):
            raise DelegateError("Adaptive admission requires MaxParallel on a new workflow")
        e = w["preparedTasks"][p["planId"]]
        if e.get("admission") or e.get("runId"):
            raise DelegateError("Plan already admitted or executed; resolve actual host state before retry")
        reasons = blockers(w, p, plans_for(w))
        if reasons:
            raise DelegateError("Task cannot dispatch: " + ", ".join(reasons))
        deps = set(p.get("dependsOn", [])) | ({p["reviewForTaskId"]} if p.get("reviewForTaskId") else set())
        receipt = path.parent / "admission.json"
        write_json(receipt, {"schemaVersion": 1, "planId": p["planId"], "planSha256": e["sha256"],
                            "admittedAt": now_iso(), "actor": identity,
                            "dependencyRuns": {tid: w["tasks"][tid]["latestRunId"] for tid in deps}})
        e["admission"] = {"path": str(receipt), "sha256": digest(receipt)}
        write_json(workflow_path(root, p["workflowId"]), w)
    finally:
        lock.release()
    print(json.dumps(spawn_payload(path, p), indent=2))
    return 0


def run_advice(ns) -> int:
    if any(not math.isfinite(x) or x < 0 for x in (ns.estimated_minutes, ns.overhead_minutes)):
        raise DelegateError("Work estimates must be finite and nonnegative")
    single = ns.coupled or not ns.independent or ns.estimated_minutes <= ns.overhead_minutes
    discussion = getattr(ns, "work_kind", "development") in ("decision", "discussion")
    direct = discussion or getattr(ns, "small_known_task", False)
    print(json.dumps({"suggestion": "main" if direct else "single-worker" if single else "delegate",
                      "complexity": ns.complexity, "workKind": getattr(ns, "work_kind", "development"),
                      "considerIndependentReview": ns.complexity == "high-risk", "estimatesOnly": True,
                      "reason": "Main owns decisions and discussion" if discussion else
                      "Main explicitly identified small known low-risk work" if direct else
                      "Keep small or coupled development in one coherent worker" if single else
                      "Independent worker tasks may overlap planning and review",
                      "decisionOwner": "main; select actual backend, model and effort using host availability and task needs"}))
    return 0
