from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/codex-with-cc/scripts"))
from codex_with_cc_runtime import metrics


def test_metrics_sum_retries_keep_missing_cost_unknown(tmp_path, monkeypatch):
    w = {"workflowId": "w", "runs": {"a": {"reportStatus": "DONE"}, "b": {}},
         "tasks": {"t": {"runs": ["a", "b"]}}}
    for rid in ("a", "b"):
        (tmp_path / f"config_{rid}.json").write_text(json.dumps({"taskId": "t", "role": "implementer", "codexThreadId": "same"}))
    (tmp_path / "status_a.json").write_text(json.dumps({"status": "completed", "retryCount": 1,
        "attempts": [{"usage": {"input_tokens": 10, "output_tokens": 2}}, {"usage": {"input_tokens": 20, "output_tokens": 3}}],
        "usage": {"input_tokens": 20, "output_tokens": 3}, "totalCostUsd": .4}))
    (tmp_path / "status_b.json").write_text(json.dumps({"status": "interrupted"}))
    calls = []
    def host(thread):
        calls.append(thread)
        return None
    monkeypatch.setattr(metrics, "host_usage", host)
    r = metrics.workflow_metrics(tmp_path, w)
    assert r["knownWorkerTokens"] == 35
    assert r["runs"][1]["workerTokens"] is None
    assert r["runs"][1]["workerReportedCostUsd"] is None
    assert r["billingTotalUsd"] is None
    assert r["costCoverageRuns"] == 1
    assert r["reworkRuns"] == 1 and r["transportRetries"] == 1
    assert calls == ["same"]


def test_partial_retry_usage_is_labeled(tmp_path, monkeypatch):
    w = {"workflowId": "w", "runs": {"a": {}}, "tasks": {}}
    (tmp_path / "config_a.json").write_text("{}")
    (tmp_path / "status_a.json").write_text(json.dumps({"status": "completed", "attemptCount": 2,
        "usage": {"input_tokens": 9, "output_tokens": 1}}))
    r = metrics.workflow_metrics(tmp_path, w)
    assert r["runs"][0]["tokenCoverage"] == "last-attempt-only"
    assert r["workerReportedCostUsdSubtotal"] is None
