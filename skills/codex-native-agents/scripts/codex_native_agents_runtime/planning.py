"""Main-owned decisions and deterministic admission checks; never starts a model."""

from __future__ import annotations

import math
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
    multi_agent_mode: str = "unknown",
    delegation_request: str = "none",
    user_restriction: str = "none",
    main_work_available: bool = False,
) -> dict:
    if (
        complexity not in {"simple", "normal", "complex", "high-risk"}
        or any(not math.isfinite(n) or n < 0 for n in (estimated_minutes, overhead_minutes))
    ):
        raise ContractError("Invalid complexity or work estimate")
    if multi_agent_mode not in {"enabled", "explicit-only", "disabled", "unknown"}:
        raise ContractError("Invalid multi-agent mode")
    if delegation_request not in {"none", "user", "agents", "skill"}:
        raise ContractError("Invalid delegation request source")
    if user_restriction not in {"none", "no-agents", "serial"}:
        raise ContractError("Invalid user restriction")
    # Caller supplies the active instructions; advice never authorizes dispatch.
    reasons = []
    if user_restriction != "none":
        reasons.append(("user-restriction", f"User requires {user_restriction} execution."))
    if multi_agent_mode == "disabled":
        reasons.append(("mode-disabled", "The task's host mode prohibits delegation."))
    elif multi_agent_mode == "unknown":
        reasons.append(("mode-unknown", "Read the current host mode before recommending dispatch."))
    elif multi_agent_mode == "explicit-only" and delegation_request == "none":
        reasons.append(("explicit-request-missing", "This mode needs an explicit user, AGENTS or applicable skill request."))
    if coupled:
        reasons.append(("coupled-work", "The candidate work is tightly coupled to main's changes."))
    if not independent:
        reasons.append(("no-independent-task", "No bounded independent worker task has been identified."))
    if not main_work_available:
        reasons.append(("no-concurrent-main-work", "Main has no useful independent work to do while the worker runs."))
    if estimated_minutes <= overhead_minutes:
        reasons.append(("overhead-exceeds-benefit", "Expected saved work does not exceed dispatch and review overhead."))
    return {
        "execution": "main" if reasons else "native",
        "profile": "strict" if high_risk or complexity == "high-risk" else "standard",
        "reason": (
            " ".join(reason for _, reason in reasons)
            if reasons
            else "The mode permits this request and independent work can overlap useful main work; preflight and dispatch."
        ),
        "reasonCodes": [code for code, _ in reasons],
        "multiAgentMode": multi_agent_mode,
        "delegationRequest": delegation_request,
        "userRestriction": user_restriction,
        "nextAction": "continue-main-or-resolve-blocker" if reasons else "preflight-and-dispatch",
        "advisoryOnly": True,
        "estimatesOnly": True,
    }


def conflicts(a: dict, b: dict) -> bool:
    return (a["writable"] or b["writable"]) and scopes_overlap(a["scopes"], b["scopes"])


def active(task: dict) -> bool:
    return bool(task.get("prepared")) or bool(
        task.get("latestSpawn") and not task["latestSpawn"].get("closure")
    )


def retry_blocker(task: dict) -> str | None:
    status = task.get("latestReportStatus")
    if status in {"NEEDS_CONTEXT", "BLOCKED"}:
        return f"{status}: return to main to resolve inputs, environment or permissions; replan instead of escalating"
    if status is None:
        terminal = (task.get("latestClose") or {}).get("terminalEvidence") or {}
        if terminal.get("event") != "turn_aborted":
            return "Missing verified failure report or interruption; return to main"
    return None


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
    from .routing import escalate_route

    simulation = copy.deepcopy(workflow)
    ready, blocked, requires_escalation = [], {}, []
    for task in simulation["tasks"].values():
        if active(task) or task.get("latestReportStatus") == "DONE":
            continue
        reasons = blockers(simulation, task)
        if task.get("fallback") == "main_thread" or not task.get("requestedModel"):
            reasons.append(
                "main_thread: " + (task.get("routingReason") or "No available route")
            )
        if len(task["spawnAttempts"]) >= 2:
            reasons.append("Retry budget exhausted; return control to main")
        elif task["spawnAttempts"]:
            retry_problem = retry_blocker(task)
            if retry_problem:
                reasons.append(retry_problem)
            elif task.get("modelProfileOverride"):
                reasons.append("Explicit model profile is fixed; return to main")
            else:
                route = escalate_route(
                    task["modelProfile"],
                    capabilities=(simulation.get("policy") or {}).get("host", {}).get("models", {}),
                )
                if route.model is None:
                    reasons.append("main_thread: " + route.reason)
        if reasons:
            blocked[task["taskId"]] = reasons
        else:
            if task["spawnAttempts"]:
                requires_escalation.append(task["taskId"])
            else:
                ready.append(task["taskId"])
            task["prepared"] = {"reservation": True}
    return {
        "ready": ready,
        "blocked": blocked,
        "requiresEscalation": requires_escalation,
        "instruction": "Prepare ready tasks normally. For requiresEscalation, diagnose first and supply --escalate --escalation-cause capability|quality --escalation-note with supporting evidence; these are candidates, not automatic retries. Both share this wave's slots and scopes. Spawn the wave before waiting, then recompute after completions.",
    }


def prepare_spawn(
    workflow: dict, task_id: str, *, escalate: bool = False,
    escalation_cause: str | None = None, escalation_note: str | None = None,
) -> dict:
    from .workflow import _acceptance_snapshot, _now
    from .contract import load_contract
    from .routing import escalate_route

    policy = workflow.get("policy")
    if not policy:
        raise ContractError("Use a new workflow with host capabilities before dispatch")
    if workflow.get("status") == "accepted":
        raise ContractError("Accepted workflows are immutable")
    if not escalate and (escalation_cause is not None or escalation_note is not None):
        raise ContractError("Escalation diagnosis requires --escalate")
    task = workflow["tasks"][task_id]
    if active(task):
        raise ContractError("Task is already prepared or running")
    if len(task["spawnAttempts"]) >= 2:
        raise ContractError("Retry budget exhausted; return control to main")
    if task["spawnAttempts"] and not escalate:
        raise ContractError(
            "A retry requires --escalate; return to main when no stronger route is available"
        )
    reasons = blockers(workflow, task)
    if reasons:
        raise ContractError("Task cannot dispatch: " + ", ".join(reasons))
    if not policy.get("host"):
        raise ContractError("Host capabilities are required before dispatch")
    host = evidence.validate_capabilities(policy["host"])
    candidate = dict(task)
    if escalate:
        if len(task["spawnAttempts"]) != 1 or task.get("latestReportStatus") == "DONE":
            raise ContractError(
                "Escalation requires exactly one failed or interrupted attempt"
            )
        if task.get("modelProfileOverride"):
            raise ContractError(
                "Explicit model profile is fixed; return to main for an authorized replan"
            )
        retry_problem = retry_blocker(task)
        if retry_problem:
            raise ContractError(retry_problem)
        route = escalate_route(task["modelProfile"], capabilities=host["models"])
        candidate.update(
            modelProfile=route.profile,
            requestedModel=route.model,
            reasoningEffort=route.reasoning_effort,
            fallback=route.fallback,
            routingReason=route.reason,
        )
    if candidate.get("fallback") == "main_thread" or not candidate["requestedModel"]:
        raise ContractError(
            "No native route; return to main. " + candidate.get("routingReason", "")
        )
    expected_route = load_contract()["modelProfiles"].get(candidate["modelProfile"])
    if not expected_route or (
        candidate["requestedModel"],
        candidate["reasoningEffort"],
    ) != (expected_route["model"], expected_route["reasoningEffort"]):
        raise ContractError(
            "Registered route differs from the current contract; start a new workflow"
        )
    if candidate["reasoningEffort"] not in host["models"].get(
        candidate["requestedModel"], []
    ):
        raise ContractError(
            f"Model/effort unavailable: {candidate['requestedModel']} / "
            f"{candidate['reasoningEffort']}; return to main or explicitly replan"
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
    diagnosis = None
    if escalate:
        if escalation_cause not in {"capability", "quality"} or not (
            isinstance(escalation_note, str) and escalation_note.strip()
        ):
            raise ContractError("Escalation requires a capability/quality cause and an evidence-based escalation note")
        diagnosis = {
            "cause": escalation_cause,
            "note": escalation_note.strip(),
            "previousRunId": task.get("lastRunId"),
            "previousAgentId": task["latestSpawn"]["agentId"],
            "previousStatus": task.get("latestReportStatus"),
        }
    prepared = {
        "preparedAt": _now(),
        "taskSha256": task["taskSha256"],
        "reviewedRunId": expected_review,
        "acceptanceSnapshot": final_snapshot,
        "source": evidence.snapshot(policy["projectRoot"], policy["artifactRoot"]),
        "escalationDiagnosis": diagnosis,
        "routing": {
            "preferredModelProfile": candidate.get(
                "preferredModelProfile", candidate["modelProfile"]
            ),
            "modelProfile": candidate["modelProfile"],
            "model": candidate["requestedModel"],
            "reasoningEffort": candidate["reasoningEffort"],
            "modelProfileOverride": candidate.get("modelProfileOverride"),
            "reason": candidate.get("routingReason"),
        },
    }
    lines = [
        "[NATIVE_CODEX_AGENT_TASK]",
        f"WorkflowId: {workflow['workflowId']}",
        f"TaskId: {task_id}",
        f"Role: {task['role']}",
        f"TaskFile: {task_file}",
        f"Scope: {','.join(task['scopes'])}",
        f"ModelProfile: {candidate['modelProfile']}",
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
        "model": candidate["requestedModel"],
        "reasoning_effort": candidate["reasoningEffort"],
    }
    parameter = policy["host"]["forkParameter"]
    payload[parameter] = "none" if parameter == "fork_turns" else False
    candidate["prepared"] = prepared
    task.update(candidate)
    return payload
