"""Import native child results from original host transcripts, without a fake runner."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from .common import ARTIFACT_SCHEMA_VERSION, INVOCATION_CONTRACT, REPORT_STATUS_VALUES, DelegateError, now_iso
from .host_evidence import session_metadata, final_response, verify_plan_prompt, verify_requested_effort
from .io_utils import load_json, write_json
from .lifecycle import digest, rollout_terminal, timestamp
from .reports import parse_report_status, parse_report_role, parse_report_final_result, text_has_required_report_headings
from .routing import verified_plan


def validate_report(text: str, role: str) -> None:
    if not text_has_required_report_headings(text) or parse_report_role(text) != role:
        raise DelegateError("Native final response has an invalid report structure or role")
    status = parse_report_status(text)
    if status not in REPORT_STATUS_VALUES or status != parse_report_final_result(text):
        raise DelegateError("Native report Status and Final Result must agree")


def interruption_notice(role: str) -> str:
    return f"Status\nBLOCKED\n\nRole\n{role}\n\nSummary\nHost turn was aborted. This is a runtime notice, not a worker completion report.\n\nChanged Files\nUnknown; inspect the working tree before resuming.\n\nVerification\nNot completed; original host records turn_aborted.\n\nFindings\nExecution interrupted.\n\nFinal Result\nBLOCKED\n\nRisks Or Follow-ups\nResume with a fresh child and verify partial changes.\n"


def run_record_native(ns) -> int:
    from .workflow import update_workflow_record
    plan_path = Path(ns.plan_file).resolve()
    p, w = verified_plan(plan_path)
    if getattr(ns, "settle", False) and (w.get("lifecyclePolicy") or {}).get("policy") != "terminal-evidence":
        raise DelegateError("record-native-run -Settle requires terminal-evidence lifecycle policy")
    from .adaptive import require_current_dependencies
    require_current_dependencies(p, w)
    if p["backend"] != "codex-native":
        raise DelegateError("Native ingestion requires a native task plan")
    if w["preparedTasks"][p["planId"]].get("runId"):
        raise DelegateError("Prepared native task was already imported; prepare a fresh attempt")
    attempt = (w.get("agentAttempts") or {}).get(ns.agent_id)
    if not attempt or attempt.get("taskId") != p["taskId"] or not attempt.get("spawnRecordedAt") or attempt.get("runId"):
        raise DelegateError("Native task requires one unused recorded spawn for this TaskId")
    transcript = Path(ns.transcript_path).resolve()
    meta = session_metadata(transcript)
    if not ns.agent_id.startswith("/root/") and ns.agent_id != meta.get("id"):
        raise DelegateError("Native agent id does not match the original host thread")
    host = rollout_terminal(transcript, meta["id"], ns.agent_id, p["projectRoot"])
    prompt_evidence = verify_plan_prompt(transcript, plan_path)
    if timestamp(host["startedAt"]) < timestamp(p["createdAt"]):
        raise DelegateError("Native host turn predates task preparation")
    aborted = host["event"] == "turn_aborted"
    text, model = (interruption_notice(p["role"]), None) if aborted else final_response(transcript)
    validate_report(text, p["role"])
    if not aborted:
        verify_requested_effort(transcript, p)
    if not aborted and model != p["model"]:
        raise DelegateError("Native host model does not match the prepared task")
    root = Path(p["artifactRoot"])
    rid = "native_" + uuid.uuid4().hex
    output = root / f"native_{rid}.md"
    output.write_text(text)
    c = {"artifactSchema": ARTIFACT_SCHEMA_VERSION, "invocationContract": INVOCATION_CONTRACT,
         "runId": rid, "workflowId": p["workflowId"], "taskId": p["taskId"], "role": p["role"],
         "runnerType": "codex_native", "executionPolicy": p["executionPolicy"], "repoRoot": p["projectRoot"],
         "preparedPlanId": p["planId"],
         "reportSource": "host-interruption-notice" if aborted else "original-host-final-response",
         "codexThreadId": meta["id"], "agentId": ns.agent_id, "planPath": str(plan_path),
         "planSha256": digest(plan_path), "hostEvidence": host, "planPromptEvidence": prompt_evidence, "outputPath": str(output),
         "model": model, "dependsOn": p.get("dependsOn", []), "scope": p["scope"], "tests": p["tests"], "allowParallel": p["allowParallel"],
         "dryRun": False, "reviewForTaskId": p.get("reviewForTaskId"), "reviewForRunId": p.get("reviewForRunId"),
         "reviewKind": p.get("reviewKind"), "verifiedImplementerRuns": p.get("verifiedImplementerRuns")}
    s = {"artifactSchema": ARTIFACT_SCHEMA_VERSION, "invocationContract": INVOCATION_CONTRACT,
         "runId": rid, "workflowId": p["workflowId"], "taskId": p["taskId"], "role": p["role"],
         "runnerType": "codex_native", "codexThreadId": meta["id"], "status": "interrupted" if aborted else "completed",
         "completionSource": host["event"], "startedAt": host["startedAt"], "completedAt": host["terminalAt"],
         "models": [model], "dryRun": False, "outputPath": str(output)}
    cp, sp = root / f"config_{rid}.json", root / f"status_{rid}.json"
    write_json(cp, c)
    write_json(sp, s)
    update_workflow_record(root, p["workflowId"], p["taskId"], p["role"], p["scope"], p["tests"], p.get("dependsOn", []), rid,
        cp, sp, output, Path(p["taskFile"]), transcript, transcript, s["status"],
        review_for_task_id=p.get("reviewForTaskId"), review_kind=p.get("reviewKind"),
        review_for_run_id=p.get("reviewForRunId"), runner_type="codex_native", codex_thread_id=meta["id"],
        verified_implementer_runs=p.get("verifiedImplementerRuns"))
    result = {"runId": rid, "hostThreadId": meta["id"], "report": str(output), "lifecycle": "pending settlement"}
    if getattr(ns, "settle", False):
        from .lifecycle import record_agent_terminal
        from .packets import run_packet
        from .workflow import workflow_path
        try:
            record_agent_terminal(root, p["workflowId"], p["taskId"], ns.agent_id, transcript)
        except DelegateError as exc:
            raise DelegateError(f"Run {rid} imported; settlement failed: {exc}. Retry record-agent-terminal with the same transcript, not import.") from exc
        result["lifecycle"] = "settled"
        result["packet"] = run_packet(root, load_json(workflow_path(root, p["workflowId"])), rid)
    print(json.dumps(result))
    return 0


def verify_native(root: Path, run_id: str, config: dict, status: dict) -> dict:
    from .workflow import workflow_path
    p, w = verified_plan(Path(config["planPath"]))
    if (digest(Path(config["planPath"])) != config.get("planSha256") or p["backend"] != "codex-native"
            or Path(p["artifactRoot"]).resolve() != root.resolve()
            or config.get("preparedPlanId") != p["planId"]
            or w["preparedTasks"][p["planId"]].get("runId") != run_id):
        raise DelegateError("Native plan changed")
    for field, expected in (("runId", run_id), ("workflowId", p["workflowId"]), ("taskId", p["taskId"]),
                            ("role", p["role"]), ("runnerType", "codex_native"),
                            ("artifactSchema", ARTIFACT_SCHEMA_VERSION), ("invocationContract", INVOCATION_CONTRACT)):
        if config.get(field) != expected or status.get(field) != expected:
            raise DelegateError(f"Native {field} binding mismatch")
    if config.get("dryRun") or status.get("dryRun") or status.get("status") not in ("completed", "interrupted"):
        raise DelegateError("Native run is not a completed real host execution")
    host = config["hostEvidence"]
    original = Path(host["path"])
    actual = rollout_terminal(original, config["codexThreadId"], config["agentId"], p["projectRoot"])
    prompt_evidence = verify_plan_prompt(original, Path(config["planPath"]))
    if ((config.get("planPromptEvidence") is not None or prompt_evidence["source"] == "original-parent-encrypted-dispatch")
            and config.get("planPromptEvidence") != prompt_evidence):
        raise DelegateError("Native original dispatch evidence changed")
    aborted = host["event"] == "turn_aborted"
    if actual != host or status.get("status") != ("interrupted" if aborted else "completed") or status.get("completedAt") != host["terminalAt"]:
        raise DelegateError("Native original host evidence changed")
    if status.get("codexThreadId") != config["codexThreadId"]:
        raise DelegateError("Native thread identity mismatch")
    text, model = (interruption_notice(p["role"]), None) if aborted else final_response(original)
    output = Path(config["outputPath"])
    if not output.resolve().is_relative_to(root.resolve()) or output.read_text() != text or (not aborted and model != p["model"]) or config.get("model") != model:
        raise DelegateError("Native model/report differs from the original host response")
    validate_report(text, p["role"])
    if not aborted:
        verify_requested_effort(original, p)
    task = w.get("tasks", {}).get(p["taskId"], {})
    if run_id not in w.get("runs", {}) or run_id not in task.get("runs", []):
        raise DelegateError("Native run is missing from the workflow index")
    for key in ("scope", "tests", "allowParallel", "executionPolicy", "reviewForTaskId", "reviewForRunId", "reviewKind", "verifiedImplementerRuns"):
        if config.get(key) != p.get(key):
            raise DelegateError(f"Native {key} differs from prepared inputs")
    return {"config": config, "status": status, "workflow": w, "artifactRoot": root}


def native_execution_evidence(root: Path, workflow: dict, attempt: dict, transcript: Path) -> dict:
    rid = attempt["runId"]
    c, s = load_json(root / f"config_{rid}.json"), load_json(root / f"status_{rid}.json")
    verify_native(root, rid, c, s)
    if (attempt.get("taskId") != c["taskId"] or not attempt.get("spawnRecordedAt") or attempt.get("agentId") != c["agentId"]
            or attempt.get("codexThreadId") != c["codexThreadId"]
            or workflow.get("runs", {}).get(rid, {}).get("codexThreadId") != c["codexThreadId"]):
        raise DelegateError("Native lifecycle attempt binding mismatch")
    if transcript.resolve() != Path(c["hostEvidence"]["path"]).resolve():
        raise DelegateError("Native terminal transcript mismatch")
    return {"schemaVersion": 1, "runId": rid, "taskId": c["taskId"], "host": c["hostEvidence"],
            "runnerType": "codex_native", "runnerStatus": s["status"], "exitCode": None, "runnerPid": None,
            "configSha256": digest(root / f"config_{rid}.json"), "statusSha256": digest(root / f"status_{rid}.json"),
            "reportSha256": digest(Path(c["outputPath"]))}
