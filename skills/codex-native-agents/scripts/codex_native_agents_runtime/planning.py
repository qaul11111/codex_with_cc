"""Main-owned decisions and deterministic admission checks; never starts a model."""

from __future__ import annotations

from pathlib import Path

from .common import ContractError
from .scope import scopes_overlap
from . import evidence


def advise(
    *,
    complexity: str,
    independent: bool,
    coupled: bool,
    estimated_minutes: float,
    overhead_minutes: float,
    high_risk: bool = False,
) -> dict:
    if (
        complexity not in {"simple", "normal", "complex", "high-risk"}
        or min(estimated_minutes, overhead_minutes) < 0
    ):
        raise ContractError("Invalid complexity or work estimate")
    direct = (
        coupled
        or not independent
        or complexity == "simple"
        or estimated_minutes <= overhead_minutes
    )
    return {
        "execution": "main" if direct else "native",
        "profile": "strict" if high_risk or complexity == "high-risk" else "standard",
        "reason": (
            "Keep coupled, short or non-independent work in main."
            if direct
            else "Independent work can overlap useful main-thread work."
        ),
        "estimatesOnly": True,
    }


def conflicts(a: dict, b: dict) -> bool:
    return (a["writable"] or b["writable"]) and scopes_overlap(a["scopes"], b["scopes"])


def active(task: dict) -> bool:
    return bool(task.get("prepared")) or bool(
        task.get("latestSpawn") and not task["latestSpawn"].get("closure")
    )


def blockers(workflow: dict, task: dict) -> list[str]:
    problems = []
    for dep in task.get("dependsOn", []):
        other = workflow["tasks"][dep]
        if (
            other.get("latestReportStatus") != "DONE"
            or not other.get("latestClose")
            or active(other)
        ):
            problems.append("dependency:" + dep)
    if task["role"] == "reviewer":
        target = workflow["tasks"][task["reviewForTaskId"]]
        if (
            target.get("latestReportStatus") != "DONE"
            or not target.get("latestClose")
            or active(target)
        ):
            problems.append("review target is not settled")
    if task["role"] == "final-verifier":
        implementers = [
            t for t in workflow["tasks"].values() if t["role"] == "implementer"
        ]
        if not implementers:
            problems.append("no implementation to verify")
        for target in implementers:
            if active(target) or not target.get("latestClose"):
                problems.append("implementation is not settled")
            for review in target["reviews"].values():
                if (
                    not review
                    or review["decision"] != "accepted"
                    or review["reviewedRunId"] != target["lastRunId"]
                ):
                    problems.append("current review is missing")
                else:
                    reviewer = workflow["tasks"][review["reviewerTaskId"]]
                    if active(reviewer) or not reviewer.get("latestClose"):
                        problems.append("review is not settled")
    running = [
        other
        for other in workflow["tasks"].values()
        if other is not task and active(other)
    ]
    policy = workflow.get("policy") or {}
    if len(running) >= policy.get("host", {}).get("maxAgents", 1):
        problems.append("concurrency limit")
    for other in running:
        if not task["parallel"] or not other["parallel"] or conflicts(task, other):
            problems.append("active scope/serial task:" + other["taskId"])
    main_scopes = policy.get("mainScopes", [])
    if main_scopes and scopes_overlap(main_scopes, task["scopes"]):
        problems.append("main-thread reserved scope")
    return problems


def ready_tasks(workflow: dict) -> dict:
    import copy

    simulation = copy.deepcopy(workflow)
    ready, blocked = [], {}
    for task in simulation["tasks"].values():
        if active(task) or task.get("latestReportStatus") == "DONE":
            continue
        reasons = blockers(simulation, task)
        if reasons:
            blocked[task["taskId"]] = reasons
        else:
            ready.append(task["taskId"])
            task["prepared"] = {"reservation": True}
    return {
        "ready": ready,
        "blocked": blocked,
        "instruction": "Prepare and spawn this ready wave before waiting; recompute after completions.",
    }


def prepare_spawn(workflow: dict, task_id: str, *, escalate: bool = False) -> dict:
    from .workflow import _acceptance_snapshot, _now
    from .contract import load_contract

    policy = workflow.get("policy")
    if not policy:
        raise ContractError("Use a new workflow with host capabilities before dispatch")
    if workflow.get("status") == "accepted":
        raise ContractError("Accepted workflows are immutable")
    task = workflow["tasks"][task_id]
    if active(task):
        raise ContractError("Task is already prepared or running")
    if len(task["spawnAttempts"]) >= 2:
        raise ContractError("Retry budget exhausted; return control to main")
    reasons = blockers(workflow, task)
    if reasons:
        raise ContractError("Task cannot dispatch: " + ", ".join(reasons))
    if not policy.get("host"):
        raise ContractError("Host capabilities are required before dispatch")
    if escalate:
        if len(task["spawnAttempts"]) != 1 or task.get("latestReportStatus") == "DONE":
            raise ContractError(
                "Escalation requires exactly one failed or interrupted attempt"
            )
        profiles = list(load_contract()["modelProfiles"])
        index = profiles.index(task["modelProfile"])
        selected = profiles[min(index + 1, len(profiles) - 1)]
        route = load_contract()["modelProfiles"][selected]
        if route["reasoningEffort"] not in policy["host"]["models"]["gpt-6-astra"]:
            raise ContractError("Escalated Astra effort unavailable")
        task.update(
            modelProfile=selected,
            requestedModel=route["model"],
            reasoningEffort=route["reasoningEffort"],
        )
    if task["reasoningEffort"] not in policy["host"]["models"]["gpt-6-astra"]:
        raise ContractError(
            "Astra effort unavailable; keep work in main or explicitly replan"
        )
    expected_review = None
    if task["role"] == "reviewer":
        target = workflow["tasks"][task["reviewForTaskId"]]
        if not target["lastRunId"] or active(target) or not target.get("latestClose"):
            raise ContractError("Reviewer requires a settled implementer run")
        expected_review = target["lastRunId"]
    final_snapshot = None
    if task["role"] == "final-verifier":
        final_snapshot = _acceptance_snapshot(workflow["tasks"])
        if not final_snapshot or any(not all(item.values()) for item in final_snapshot):
            raise ContractError("Final verifier requires current accepted reviews")
        for item in final_snapshot:
            for kind in ("spec", "quality"):
                review = workflow["tasks"][item["implementerTaskId"]]["reviews"][kind]
                if review["reviewedRunId"] != item["implementerRunId"]:
                    raise ContractError("Final verifier inputs include stale reviews")
    task_file = Path(task["taskFile"]).resolve()
    if evidence.digest(task_file) != task["taskSha256"]:
        raise ContractError("Registered TaskFile changed")
    prepared = {
        "preparedAt": _now(),
        "taskSha256": task["taskSha256"],
        "reviewedRunId": expected_review,
        "acceptanceSnapshot": final_snapshot,
        "source": evidence.snapshot(policy["projectRoot"], policy["artifactRoot"]),
    }
    task["prepared"] = prepared
    lines = [
        "[NATIVE_CODEX_AGENT_TASK]",
        f"WorkflowId: {workflow['workflowId']}",
        f"TaskId: {task_id}",
        f"Role: {task['role']}",
        f"TaskFile: {task_file}",
        f"Scope: {','.join(task['scopes'])}",
        f"ModelProfile: {task['modelProfile']}",
        f"Writable: {str(task['writable']).lower()}",
        f"Parallel: {str(task['parallel']).lower()}",
        "DispatcherRole: main",
        "[/NATIVE_CODEX_AGENT_TASK]",
        "Read the TaskFile. Use native tools only; do not delegate. Return the exact structured report.",
    ]
    if expected_review:
        lines.append("ReviewForRunId: " + expected_review)
    if final_snapshot is not None:
        lines.append("FinalInputs: " + str(final_snapshot))
    payload = {
        "task_name": task_id.replace("-", "_")
        + "_"
        + evidence.fingerprint(prepared)[:10],
        "message": "\n".join(lines),
        "model": task["requestedModel"],
        "reasoning_effort": task["reasoningEffort"],
    }
    parameter = policy["host"]["forkParameter"]
    payload[parameter] = "none" if parameter == "fork_turns" else False
    return payload
