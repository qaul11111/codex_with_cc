"""Bounded, read-only delivery views. Original artifacts remain authoritative.

Packets are observations, never substitutes for artifact verification or main
review. A cached acceptance decision is deliberately not presented as current.
"""
from __future__ import annotations

import json
from pathlib import Path

from .io_utils import load_json
from .reports import report_section, parse_report_status, parse_report_role, parse_report_final_result, text_has_required_report_headings


def excerpt(text: str, limit: int) -> dict:
    return {"text": text[:limit], "truncated": len(text) > limit, "originalChars": len(text), "missing": not bool(text)}


def run_packet(root: Path, workflow: dict, run_id: str) -> dict:
    run = workflow["runs"][run_id]
    config_path = Path(run["configPath"])
    config = load_json(config_path)
    status_path = Path(run["statusPath"])
    status = load_json(status_path)
    report_path = Path(config["outputPath"])
    text = report_path.read_text() if report_path.is_file() else ""
    attempts = [a for a in workflow.get("agentAttempts", {}).values() if a.get("runId") == run_id]
    return {"runId": run_id, "taskId": run["taskId"], "role": config.get("role"),
            "recordedStatus": status.get("status"), "reportStatus": parse_report_status(text) or "INVALID_OR_MISSING",
            "reportStructureValid": bool(text_has_required_report_headings(text) and
                parse_report_role(text) == config.get("role") and parse_report_status(text) == parse_report_final_result(text)),
            "summary": excerpt(report_section(text, "Summary"), 320),
            "changedFiles": excerpt(report_section(text, "Changed Files"), 640),
            "verification": excerpt(report_section(text, "Verification"), 480),
            "findings": excerpt(report_section(text, "Findings"), 480),
            "risks": excerpt(report_section(text, "Risks Or Follow-ups"), 480),
            "lifecycle": [{"agentId": a.get("agentId"), "settled": bool(a.get("settledAt")),
                           "closeStatus": a.get("closeStatus")} for a in attempts],
            "processLifecycle": [{"processPid": a.get("processPid"), "settled": bool(a.get("settledAt")),
                                  "receiptPath": a.get("receiptPath")} for a in workflow.get("processAttempts", {}).values() if a.get("runId") == run_id],
            "failureReason": status.get("failureReason"),
            "artifacts": {"report": str(report_path), "config": str(config_path), "status": str(status_path)},
            "advisoryOnly": True, "requiresArtifactVerification": True}


def review_packet(root: Path, workflow_id: str, limit: int = 20) -> dict:
    from .workflow import workflow_path
    path = workflow_path(root, workflow_id)
    workflow = load_json(path)
    runs = [t["latestRunId"] for _, t in sorted(workflow.get("tasks", {}).items()) if t.get("latestRunId")]
    review = workflow.get("mainReview") or {}
    return {"schemaVersion": 1, "workflowId": workflow_id, "advisoryOnly": True,
            "requiresArtifactVerification": True, "workflowPath": str(path),
            "runs": [run_packet(root, workflow, rid) for rid in runs[:limit]],
            "omittedRuns": max(0, len(runs) - limit), "totalLatestRuns": len(runs),
            "recordedAcceptance": workflow.get("finalAcceptance", {}).get("status"),
            "acceptanceFreshness": "not-verified; run verify-workflow after main review",
            "mainReviewArtifacts": {key: review.get(key) for key in ("evidencePath", "reviewPath")}}


def run_review_packet(ns) -> int:
    from .artifacts import resolve_artifact_root
    root = resolve_artifact_root(ns.artifact_root, workflow_id=ns.workflow_id)
    print(json.dumps(review_packet(root, ns.workflow_id, ns.limit), ensure_ascii=False, sort_keys=True))
    return 0
