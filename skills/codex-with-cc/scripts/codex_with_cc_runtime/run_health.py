"""Read-only status observations. Never turn a missing process into success."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .io_utils import load_json


def observed_status(status: dict) -> str:
    recorded = str(status.get("status") or "unknown")
    if recorded not in ("starting", "running"):
        return recorded
    pid = status.get("pid")
    if type(pid) is not int or pid <= 0:
        return "unknown-process"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "abandoned"
    except (PermissionError, OSError):
        return "unknown-process"
    heartbeat = status.get("lastHeartbeatAt") or status.get("updatedAt")
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(str(heartbeat).replace("Z", "+00:00"))).total_seconds()
    except (ValueError, TypeError):
        return "unknown-heartbeat"
    if age > max(120, 4 * int(status.get("heartbeatSeconds") or 15)):
        return "stale-process"  # PID may have been reused; do not signal it.
    return recorded


def inspect_runs(root: Path, workflow_id: str | None = None) -> list[dict]:
    rows = []
    for path in sorted(root.glob("status_*.json")):
        status = load_json(path)
        if workflow_id and status.get("workflowId") != workflow_id:
            continue
        rows.append({"runId": status.get("runId"), "workflowId": status.get("workflowId"),
                     "recordedStatus": status.get("status"), "observedStatus": observed_status(status),
                     "lastUpdatedAt": status.get("updatedAt"), "path": str(path)})
    return rows


def run_inspect_runs(ns) -> int:
    from .artifacts import resolve_artifact_root
    root = resolve_artifact_root(ns.artifact_root, workflow_id=ns.workflow_id)
    rows = inspect_runs(root, ns.workflow_id)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 1 if any(r["observedStatus"] in ("abandoned", "stale-process", "unknown-process", "unknown-heartbeat") for r in rows) else 0
