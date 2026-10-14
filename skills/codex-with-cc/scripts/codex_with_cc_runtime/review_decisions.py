"""Explicit main review of non-blocking concerns; preserve worker reports."""
from __future__ import annotations

from pathlib import Path
from .common import DelegateError
from .io_utils import load_json
from .lifecycle import digest


def reviewable(task: dict) -> bool:
    return (task.get("status") == "completed" and task.get("lastReportStatus") in ("DONE", "DONE_WITH_CONCERNS")
            and task.get("lastReportStatus") == task.get("lastReportFinalResult"))


def validate_decisions(workflow: dict, data: dict) -> dict:
    expected = {tid: t for tid, t in workflow.get("tasks", {}).items() if t.get("lastReportStatus") == "DONE_WITH_CONCERNS"}
    rows = data.get("decisions")
    if not isinstance(rows, list):
        raise DelegateError("Concern decisions must contain a decisions array")
    indexed = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("taskId") in indexed:
            raise DelegateError("Concern decisions contain invalid or duplicate tasks")
        tid = row.get("taskId"); task = expected.get(tid)
        if not task or not reviewable(task) or row.get("runId") != task.get("latestRunId"):
            raise DelegateError("Concern decision must bind a current completed DONE_WITH_CONCERNS run")
        config = load_json(Path(workflow["runs"][row["runId"]]["configPath"]))
        if row.get("reportSha256") != digest(Path(config["outputPath"])):
            raise DelegateError("Concern decision report hash is missing or stale")
        concerns = row.get("concerns")
        if not isinstance(concerns, list) or not concerns:
            raise DelegateError("Each concern decision needs explicit findings and dispositions")
        for c in concerns:
            if (not isinstance(c, dict) or c.get("disposition") not in ("accepted-risk", "resolved", "not-applicable")
                    or any(not isinstance(c.get(k), str) or not c[k].strip() for k in ("finding", "reason", "evidence"))):
                raise DelegateError("Concern disposition requires finding, reason and evidence")
        indexed[tid] = row
    if set(indexed) != set(expected):
        raise DelegateError("Every current DONE_WITH_CONCERNS task requires an explicit main decision")
    return data


def verify_decisions(root: Path, workflow: dict) -> None:
    ref = (workflow.get("mainReview") or {}).get("concernDecisions")
    if ref is None:
        validate_decisions(workflow, {"decisions": []})
        return
    path = Path(ref.get("path", ""))
    if (not path.resolve().is_relative_to((root / "checks").resolve()) or path.is_symlink()
            or not path.is_file() or digest(path) != ref.get("sha256")):
        raise DelegateError("Main concern decisions are missing or changed")
    validate_decisions(workflow, load_json(path))
