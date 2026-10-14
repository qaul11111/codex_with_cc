"""Pinned serial-execution evidence for same-task parallel scope overlaps.

Serial historical retries of the SAME implementer TaskId share scope by
definition and must not be mistaken for concurrent overlapping writes. The
exception is narrow: it applies only within one TaskId, only when each run's
pinned terminal evidence is re-verified against the untouched originals
(lifecycle.execution_evidence recomputed and compared to the stored value,
which binds the original transcript and config/status/report hashes), and only
when that evidence proves strict serial execution.

The candidate execution interval is the authenticated host terminal turn
startedAt to the ORIGINAL PINNED runner status updatedAt (hash-bound by the
re-verified evidence). Host terminalAt is never used as the end bound: the
carrier's final relay can outlast the next child spawn without any worker
write overlap. All timing comes from the original records; editable aggregate
timestamps, RunId ordering, and the current clock are never used.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import DelegateError
from .io_utils import load_json
from .lifecycle import execution_evidence, timestamp


def _single_attempt(workflow: dict[str, Any], task_id: str, run_id: str) -> dict[str, Any]:
    matches = [
        attempt
        for attempt in (workflow.get("agentAttempts") or {}).values()
        if isinstance(attempt, dict)
        and str(attempt.get("runId") or "") == run_id
        and str(attempt.get("taskId") or "") == task_id
    ]
    if len(matches) != 1:
        raise DelegateError(
            f"serial scope evidence requires exactly one task/run/native-thread attempt "
            f"for TaskId {task_id} RunId {run_id}; found {len(matches)}"
        )
    return matches[0]


def _reverified_execution(root: Path, workflow: dict[str, Any], attempt: dict[str, Any], task_id: str, run_id: str) -> dict[str, Any]:
    policy = workflow.get("lifecyclePolicy") if isinstance(workflow.get("lifecyclePolicy"), dict) else {}
    if policy.get("policy") != "terminal-evidence":
        raise DelegateError(
            f"serial scope evidence requires the terminal-evidence lifecycle policy for TaskId {task_id} RunId {run_id}"
        )
    stored = attempt.get("executionEvidence")
    if not isinstance(stored, dict):
        raise DelegateError(f"missing pinned terminal evidence for TaskId {task_id} RunId {run_id}")
    transcript = Path(str((stored.get("host") or {}).get("path") or ""))
    # execution_evidence re-derives everything from the originals: non-dry,
    # non-fallback, non-recovered terminal runner, exited PID (released
    # lease), original transcript inside the sessions root, and
    # config/status/report hashes. The stored value is never trusted.
    actual = execution_evidence(root, workflow, attempt, transcript)
    if actual != stored:
        raise DelegateError(f"pinned terminal evidence changed for TaskId {task_id} RunId {run_id}")
    return actual


def _execution_interval(root: Path, evidence: dict[str, Any], task_id: str, run_id: str) -> tuple[Any, Any]:
    # status.updatedAt is pinned: the re-verified evidence binds statusSha256,
    # so the file read here is exactly the original runner record.
    status = load_json(Path(root) / f"status_{run_id}.json")
    host = evidence.get("host") if isinstance(evidence.get("host"), dict) else {}
    start = timestamp(host.get("startedAt"))
    end = timestamp(status.get("completedAt") if status.get("runnerType") == "codex_native" else status.get("updatedAt"))
    terminal = timestamp(host.get("terminalAt"))
    if not (start <= end <= terminal):
        raise DelegateError(
            f"runner completion lies outside its authenticated host turn for TaskId {task_id} RunId {run_id}"
        )
    return start, end


def prove_serial_same_task(root: Path | str, workflow: dict[str, Any], task_id: str, left_run: str, right_run: str) -> None:
    """Raise DelegateError unless pinned terminal evidence proves strict serial execution.

    Only the evidence of the two runs in the overlapping pair is validated;
    unrelated attempts (for example an in-flight final verifier) are not
    required to be settled here, and the whole lifecycle gate is unchanged.
    """
    root = Path(root)
    intervals: dict[str, tuple[Any, Any]] = {}
    for run_id in (left_run, right_run):
        if workflow.get("runs", {}).get(run_id, {}).get("runnerType") == "claude_process":
            from .process_run import verify_process
            config, status = load_json(root / f"config_{run_id}.json"), load_json(root / f"status_{run_id}.json")
            verify_process(root, run_id, config, status)
            if config.get("taskId") != task_id:
                raise DelegateError("Serial process task identity mismatch")
            intervals[run_id] = timestamp(status["startedAt"]), timestamp(status["completedAt"])
            if intervals[run_id][0] > intervals[run_id][1]:
                raise DelegateError("Process interval is invalid")
            continue
        attempt = _single_attempt(workflow, task_id, run_id)
        evidence = _reverified_execution(root, workflow, attempt, task_id, run_id)
        intervals[run_id] = _execution_interval(root, evidence, task_id, run_id)
    if intervals[left_run][0] == intervals[right_run][0]:
        raise DelegateError(f"uncertain execution ordering for TaskId {task_id} runs {left_run} and {right_run}")
    earlier, later = (left_run, right_run) if intervals[left_run][0] < intervals[right_run][0] else (right_run, left_run)
    if not intervals[earlier][1] < intervals[later][0]:
        raise DelegateError(
            f"serial execution not proven for TaskId {task_id}: earlier runner {earlier} "
            f"did not finish before the later host turn {later} started"
        )
