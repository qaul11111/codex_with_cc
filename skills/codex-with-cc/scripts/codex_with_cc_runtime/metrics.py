"""Whole-chain observations with explicit missing data and no inferred API prices."""
from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

from .common import DelegateError, now_iso
from .io_utils import load_json
from .lifecycle import sessions_root, timestamp
from .run_health import observed_status
from .ccviz_parser import token_counts


def host_usage(thread: str) -> dict | None:
    paths = list(sessions_root().rglob(f"*{thread}.jsonl")) if thread else []
    if len(paths) != 1:
        return None
    from .host_evidence import session_metadata
    if session_metadata(paths[0]).get("id") != thread:
        raise DelegateError("Usage transcript thread id mismatch")
    usage, model, observed = None, None, None
    with paths[0].open() as handle:
        for line in handle:
            try:
                r = json.loads(line)
            except ValueError:
                continue  # Active main-thread log may have a partial trailing record.
            p = r.get("payload") or {}
            if r.get("type") == "turn_context":
                model = p.get("model", model)
            if r.get("type") == "event_msg" and p.get("type") == "token_count":
                info = p.get("info") or {}
                if isinstance(info.get("total_token_usage"), dict):
                    usage, observed = info["total_token_usage"], r.get("timestamp")
    if usage is None:
        return None
    return {"threadId": thread, "path": str(paths[0]), "model": model, "observedAt": observed,
            "inputTokens": usage.get("input_tokens"), "cachedInputTokens": usage.get("cached_input_tokens"),
            "outputTokens": usage.get("output_tokens"), "reasoningOutputTokens": usage.get("reasoning_output_tokens"),
            "totalTokens": usage.get("total_tokens")}


def capture_baseline() -> dict | None:
    return host_usage(os.environ.get("CODEX_THREAD_ID", ""))


def workflow_metrics(root: Path, w: dict) -> dict:
    rows = []
    seen_threads = set()
    host_rows = []
    for rid, run in w.get("runs", {}).items():
        cp, sp = root / f"config_{rid}.json", root / f"status_{rid}.json"
        if not cp.exists() or not sp.exists():
            rows.append({"runId": rid, "missingArtifacts": True})
            continue
        c, s = load_json(cp), load_json(sp)
        attempts = s.get("attempts") or []
        token_rows = [token_counts(a["usage"]) for a in attempts if a.get("usage")]
        coverage = "complete" if token_rows and len(token_rows) == len(attempts) else "partial"
        if not token_rows and s.get("usage"):
            token_rows = [token_counts(s["usage"])]
            coverage = "complete" if int(s.get("attemptCount", 1)) == 1 else "last-attempt-only"
        count = sum(t["total"] for t in token_rows) if token_rows else None
        if count is None:
            coverage = "unavailable"
        start = s.get("startedAt")
        end = s.get("completedAt") or (s.get("updatedAt") if s.get("status") in ("completed", "failed", "interrupted") else None)
        duration = None
        if start and end:
            duration = max(0, (timestamp(end) - timestamp(start)).total_seconds())
        worker_start = s.get("workerStartedAt")
        queue_seconds = max(0, (timestamp(worker_start) - timestamp(start)).total_seconds()) if start and worker_start else None
        row = {"runId": rid, "taskId": c.get("taskId"), "role": c.get("role"),
               "runnerType": c.get("runnerType"), "configuredModel": c.get("model"), "actualModels": s.get("models"),
               "recordedStatus": s.get("status"), "observedStatus": observed_status(s),
               "reportStatus": run.get("reportStatus"), "dryRun": bool(c.get("dryRun")),
               "retryCount": s.get("retryCount", 0), "workerTokens": count, "tokenCoverage": coverage,
               "workerReportedCostUsd": s.get("totalCostUsd"), "costSource": "cli-or-provider-estimate-not-invoice" if s.get("totalCostUsd") is not None else "unavailable",
               "costCoverageAttempts": s.get("costCoverageAttempts"),
               "durationSeconds": duration, "queueSeconds": queue_seconds, "startedAt": start, "finishedAt": end}
        rows.append(row)
        thread = c.get("codexThreadId")
        if thread and thread not in seen_threads:
            seen_threads.add(thread)
            usage = host_usage(thread)
            host_rows.append({"kind": "native-worker" if c.get("runnerType") == "codex_native" else "carrier",
                              "threadId": thread, "usage": usage})
    baseline = w.get("mainUsageBaseline")
    main = None
    if baseline:
        current = host_usage(baseline["threadId"])
        if current:
            keys = ("inputTokens", "cachedInputTokens", "outputTokens", "reasoningOutputTokens", "totalTokens")
            main = {"threadId": baseline["threadId"], "from": baseline.get("observedAt"), "to": current.get("observedAt"),
                    "usage": {k: current[k] - baseline[k] if type(current.get(k)) is int and type(baseline.get(k)) is int and current[k] >= baseline[k] else None for k in keys},
                    "attribution": "main-session delta since configuration; may include other work and lags active output"}
    costs = [r["workerReportedCostUsd"] for r in rows if r.get("workerReportedCostUsd") is not None and not r.get("dryRun")]
    tokens = [r["workerTokens"] for r in rows if r.get("workerTokens") is not None and not r.get("dryRun")]
    counts = Counter(r.get("role", "unknown") for r in rows if not r.get("dryRun"))
    timed = [r for r in rows if not r.get("dryRun") and r.get("startedAt") and r.get("finishedAt")]
    span = (max(timestamp(r["finishedAt"]) for r in timed) - min(timestamp(r["startedAt"]) for r in timed)).total_seconds() if timed else None
    return {"schemaVersion": 1, "workflowId": w["workflowId"], "observedAt": now_iso(),
            "profile": (w.get("executionPolicy") or {}).get("profile", "strict"),
            "recordedAcceptance": w.get("finalAcceptance"), "runCount": len(rows), "runsByRole": dict(counts),
            "reworkRuns": sum(max(0, len(t.get("runs", [])) - 1) for t in w.get("tasks", {}).values()),
            "transportRetries": sum(r.get("retryCount", 0) for r in rows),
            "observedExecutionSpanSeconds": span, "timingCoverageRuns": len(timed),
            "knownWorkerTokens": sum(tokens) if tokens else None,
            "workerReportedCostUsdSubtotal": sum(costs) if costs else None,
            "costCoverageRuns": len(costs), "runs": rows, "hostThreads": host_rows, "mainThread": main,
            "billingTotalUsd": None, "limitations": ["Missing usage is unavailable, never zero.",
            "Provider/CLI dollar values are estimates, not invoices; Codex subscription usage is not converted to dollars.",
            "Historical runs without timestamps or a main baseline have incomplete duration or main-thread attribution.",
            "Execution span covers known run timestamps, including gaps; it excludes planning and later main review.",
            "Recorded acceptance is not a fresh content or workflow verification."]}


def run_metrics(ns) -> int:
    from .artifacts import resolve_artifact_root
    from .workflow import workflow_path
    root = resolve_artifact_root(ns.artifact_root, workflow_id=ns.workflow_id)
    result = workflow_metrics(root, load_json(workflow_path(root, ns.workflow_id)))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
