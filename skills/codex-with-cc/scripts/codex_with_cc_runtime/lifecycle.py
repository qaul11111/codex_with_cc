"""Host capability negotiation and evidence-backed execution settlement.

Completion is deliberately not thread closure. Local rollout files are host
evidence, not cryptographic attestations against a malicious same-user process.
Legacy workflows stay strict-close until explicitly migrated.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .common import CONTRACT, DelegateError, now_iso
from .io_utils import load_json, write_json
from .locks import acquire_file_lock

POLICIES = tuple(CONTRACT["lifecycle"]["policies"])
MAX_ROLLOUT_BYTES = 128 * 1024 * 1024
MAX_LINE_BYTES = 16 * 1024 * 1024


def sessions_root() -> Path:
    return (Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions").resolve()


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def timestamp(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("missing timezone")
        return result
    except (ValueError, TypeError) as exc:
        raise DelegateError("Lifecycle evidence requires an explicit timestamp with timezone") from exc


def capability_profile(document: dict[str, Any], policy: str) -> dict[str, Any]:
    if policy not in POLICIES:
        raise DelegateError(f"Unknown lifecycle policy: {policy}")
    if not isinstance(document, dict) or document.get("schemaVersion") != 1 or document.get("source") != "active-tool-catalog":
        raise DelegateError("Capabilities must be a version-1 active-tool-catalog snapshot")
    tools = document.get("tools")
    if not isinstance(tools, list) or not tools or not all(isinstance(t, str) and t.strip() for t in tools):
        raise DelegateError("Capabilities require a non-empty tools list")
    names = {name.rsplit(".", 1)[-1] for name in tools}
    if policy == "process-exit":
        if "exec_command" not in names or os.name != "posix" or not sessions_root().is_dir():
            raise DelegateError("process-exit requires POSIX exec_command and original main sessions")
        return {"schemaVersion": 1, "policy": policy, "source": "active-tool-catalog", "tools": sorted(set(tools)),
                "closeSupported": False, "terminalEvidenceAdapter": "posix-process-v1"}
    if "spawn_agent" not in names:
        raise DelegateError("Host does not expose spawn_agent; do not dispatch")
    if not ({"wait_agent", "list_agents"} <= names or "wait" in names):
        raise DelegateError("Host does not expose agent result/status operations; do not dispatch")
    can_close = "close_agent" in names
    if policy == "strict-close" and not can_close:
        raise DelegateError("Host lacks close_agent; strict-close preflight failed before dispatch")
    if policy == "terminal-evidence":
        if can_close:
            raise DelegateError("Host exposes close_agent; use strict-close rather than skipping available closure")
        if os.name != "posix":
            raise DelegateError("codex-rollout-v1 terminal evidence currently requires a POSIX host")
        if not sessions_root().is_dir():
            raise DelegateError("Host rollout directory is unavailable; terminal-evidence cannot be used")
    return {
        "schemaVersion": 1, "policy": policy, "source": "active-tool-catalog",
        "tools": sorted(set(tools)), "closeSupported": can_close,
        "terminalEvidenceAdapter": "codex-rollout-v1" if not can_close else None,
    }


def configure_lifecycle(root: Path, workflow_id: str, policy: str, capabilities_file: Path,
                        migrate_existing: bool = False) -> Path:
    from .workflow import empty_workflow, update_workflow_acceptance, workflow_lock_path, workflow_path
    profile = capability_profile(load_json(capabilities_file), policy)
    path = workflow_path(root, workflow_id)
    lock = acquire_file_lock(workflow_lock_path(root, workflow_id), timeout_seconds=30,
                             poll_seconds=0.05, message=lambda: f"Lifecycle configuration locked: {path}")
    try:
        workflow = load_json(path) if path.exists() else empty_workflow(workflow_id)
        previous = workflow.get("lifecyclePolicy")
        if isinstance(previous, dict) and all(previous.get(key) == value for key, value in profile.items()):
            return path
        if workflow.get("agentAttempts") or workflow.get("runs"):
            if not migrate_existing:
                raise DelegateError("Existing workflow requires explicit -MigrateExisting; no policy was changed")
            backup = path.with_name(f"{path.stem}.before-lifecycle-{uuid.uuid4().hex}.json")
            # Back up the exact bytes, preserving all reports and previous decisions.
            with backup.open("xb") as target:
                target.write(path.read_bytes())
            workflow.setdefault("lifecyclePolicyHistory", []).append({
                "previous": previous, "migratedAt": now_iso(), "backupPath": str(backup),
            })
        profile.update({"configuredAt": now_iso(), "capabilitiesSha256": digest(capabilities_file)})
        workflow["lifecyclePolicy"] = profile
        workflow["revision"] = int(workflow.get("revision") or 0) + 1
        update_workflow_acceptance(workflow)
        write_json(path, workflow)
        return path
    finally:
        lock.release()


def require_lifecycle_preflight(root: Path, workflow_id: str) -> None:
    """Backstop in the child before a real worker starts; parent checks before spawn."""
    from .workflow import workflow_path
    path = workflow_path(root, workflow_id)
    if not path.exists():
        raise DelegateError("Missing lifecycle preflight; main thread must configure-lifecycle before spawning")
    workflow = load_json(path)
    profile = workflow.get("lifecyclePolicy")
    if workflow.get("workflowId") != workflow_id or not isinstance(profile, dict):
        raise DelegateError("Missing lifecycle policy; explicitly configure-lifecycle before new worker execution")
    expected = capability_profile(profile, str(profile.get("policy")))
    if any(profile.get(key) != value for key, value in expected.items()):
        raise DelegateError("Lifecycle capability profile is inconsistent")


def rollout_terminal(path: Path, thread_id: str, agent_id: str, repo_root: str) -> dict[str, Any]:
    original = path
    path = path.resolve()
    try:
        path.relative_to(sessions_root())
    except ValueError as exc:
        raise DelegateError("Terminal evidence must be an original Codex sessions rollout") from exc
    if original.is_symlink() or not path.is_file():
        raise DelegateError("Terminal rollout must be a regular file, not a symlink")
    info = path.stat()
    if info.st_size > MAX_ROLLOUT_BYTES:
        raise DelegateError("Terminal rollout exceeds the bounded parser limit")
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise DelegateError("Terminal rollout is group/other writable")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise DelegateError("Terminal rollout has an unexpected owner")
    header = None
    active_turn = None
    terminal = None
    last_event = None
    started = None
    hasher = hashlib.sha256()
    total_bytes = 0
    with path.open("rb") as stream:
        while raw := stream.readline(MAX_LINE_BYTES + 1):
            total_bytes += len(raw)
            if total_bytes > MAX_ROLLOUT_BYTES:
                raise DelegateError("Terminal rollout exceeds the bounded parser limit")
            if len(raw) > MAX_LINE_BYTES or not raw.endswith(b"\n"):
                raise DelegateError("Terminal rollout has an oversized or incomplete record")
            hasher.update(raw)
            try:
                item = json.loads(raw)
            except (ValueError, UnicodeError) as exc:
                raise DelegateError("Malformed terminal rollout record") from exc
            if not isinstance(item, dict):
                raise DelegateError("Malformed terminal rollout object")
            payload = item.get("payload")
            if not isinstance(payload, dict):
                continue
            if item.get("type") == "session_meta":
                if header is not None:
                    raise DelegateError("Ambiguous session metadata in terminal rollout")
                header = payload
            if item.get("type") != "event_msg":
                continue
            event = payload.get("type")
            if event == "token_count":
                continue
            last_event = event
            if event == "task_started":
                if active_turn:
                    raise DelegateError("Overlapping active turns in terminal rollout")
                active_turn = payload.get("turn_id")
                started = item.get("timestamp")
                terminal = None
            elif event in ("task_complete", "turn_aborted"):
                if not active_turn or payload.get("turn_id") != active_turn:
                    raise DelegateError("Terminal event does not match the active turn")
                terminal = {"turnId": active_turn, "event": event, "startedAt": started,
                            "terminalAt": item.get("timestamp")}
                active_turn = None
    if not header or header.get("id") != thread_id:
        raise DelegateError("Terminal rollout thread id mismatch")
    if Path(str(header.get("cwd") or "")).resolve() != Path(repo_root).resolve():
        raise DelegateError("Terminal rollout project mismatch")
    source = header.get("source")
    subagent = source.get("subagent") if isinstance(source, dict) else None
    spawn = subagent.get("thread_spawn") if isinstance(subagent, dict) else None
    spawn = spawn if isinstance(spawn, dict) else {}
    if not spawn.get("parent_thread_id"):
        raise DelegateError("Terminal rollout lacks host child-thread provenance")
    if header.get("parent_thread_id") not in (None, spawn["parent_thread_id"]):
        raise DelegateError("Terminal rollout parent-thread mismatch")
    if agent_id.startswith("/root/") and spawn.get("agent_path") != agent_id:
        raise DelegateError("Terminal rollout agent handle mismatch")
    if active_turn or not terminal or last_event not in ("task_complete", "turn_aborted"):
        raise DelegateError("Host execution has not reached a final terminal event")
    if timestamp(terminal["terminalAt"]) < timestamp(terminal["startedAt"]):
        raise DelegateError("Terminal rollout timestamps are out of order")
    after = path.stat()
    if (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise DelegateError("Terminal rollout changed while it was being inspected")
    return {**terminal, "path": str(path), "sha256": hasher.hexdigest(),
            "threadId": thread_id, "parentThreadId": spawn["parent_thread_id"]}


def execution_evidence(root: Path, workflow: dict[str, Any], attempt: dict[str, Any],
                       transcript: Path) -> dict[str, Any]:
    if os.name != "posix":
        raise DelegateError("codex-rollout-v1 terminal evidence currently requires a POSIX host")
    run_id = attempt.get("runId")
    thread_id = attempt.get("codexThreadId") or attempt.get("agentId")
    if not run_id or not attempt.get("spawnRecordedAt"):
        raise DelegateError("Terminal evidence requires a recorded spawn and a bound run")
    run = (workflow.get("runs") or {}).get(run_id)
    if not isinstance(run, dict) or run.get("taskId") != attempt.get("taskId"):
        raise DelegateError("Terminal evidence run/task binding mismatch")
    config_path, status_path = root / f"config_{run_id}.json", root / f"status_{run_id}.json"
    config, status = load_json(config_path), load_json(status_path)
    if config.get("runnerType") == "codex_native":
        from .native_run import native_execution_evidence
        return native_execution_evidence(root, workflow, attempt, transcript)
    for record in (run, config, status):
        for key, expected in (("runId", run_id), ("taskId", attempt["taskId"]), ("codexThreadId", thread_id)):
            if record.get(key) != expected:
                raise DelegateError(f"Terminal evidence {key} binding mismatch")
        if record.get("dryRun"):
            raise DelegateError("Dry-run execution cannot provide terminal acceptance evidence")
    for record in (config, status):
        if record.get("workflowId") != workflow.get("workflowId") or record.get("trustedLocalFallback"):
            raise DelegateError("Terminal evidence workflow/provenance mismatch")
    if status.get("statusRecoveredFromReport"):
        raise DelegateError("Report-recovered status is not process completion evidence")
    if any(item.get("dryRun") for item in status.get("attempts") or []):
        raise DelegateError("Dry-run attempts cannot provide terminal acceptance evidence")
    if status.get("status") not in ("completed", "failed", "interrupted") or type(status.get("exitCode")) is not int:
        raise DelegateError("Runner has not recorded a terminal status and exit code")
    if run.get("status") != status["status"] or attempt.get("runStatus") != status["status"]:
        raise DelegateError("Terminal evidence run status mismatch")
    pid = status.get("pid")
    if type(pid) is not int or pid <= 0:
        raise DelegateError("Runner PID is missing; cannot prove execution has exited")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        raise DelegateError("Cannot verify runner PID liveness") from exc
    else:
        raise DelegateError("Runner PID is still alive (or reused); terminal proof is unavailable")
    host = rollout_terminal(transcript, str(thread_id), str(attempt["agentId"]), str(config.get("repoRoot") or ""))
    if host["event"] == "turn_aborted" and status["status"] == "completed":
        raise DelegateError("Interrupted host turn cannot certify successful execution")
    # Bind the host's final turn to this exact runner, not another turn in the same thread.
    recorded = timestamp(status.get("updatedAt"))
    if not timestamp(host["startedAt"]) <= recorded <= timestamp(host["terminalAt"]):
        raise DelegateError("Runner completion lies outside the host terminal turn")
    from .artifacts import verify_artifacts
    verify_artifacts(str(run_id), str(root), recover_status=False, allow_interrupted=True)
    output = Path(str(config["outputPath"]))
    return {"schemaVersion": 1, "runId": run_id, "taskId": attempt["taskId"],
            "host": host, "runnerStatus": status["status"], "exitCode": status["exitCode"],
            "runnerPid": pid, "configSha256": digest(config_path), "statusSha256": digest(status_path),
            "reportSha256": digest(output) if output.is_file() else None}


def lifecycle_notice(workflow: dict[str, Any]) -> str:
    """Describe execution separately from a host's unavailable close interface."""
    if (workflow.get("lifecyclePolicy") or {}).get("closeSupported") is not False:
        return ""
    attempts = list((workflow.get("agentAttempts") or {}).values())
    if attempts and all(a.get("settledAt") and a.get("executionEvidence")
                        and a.get("executionStatus") in ("completed", "failed", "interrupted") for a in attempts):
        return "执行已结束；宿主不提供线程关闭接口。"
    if attempts:
        return "执行终态尚未全部核验；宿主不提供线程关闭接口。"
    return "尚未派发子任务；宿主不提供线程关闭接口。"


def lifecycle_gate(workflow: dict[str, Any]) -> dict[str, Any] | None:
    profile = workflow.get("lifecyclePolicy") or {"policy": "strict-close"}
    if not isinstance(profile, dict):
        return {"status": "invalid-lifecycle-policy"}
    policy = profile.get("policy")
    attempts = [a for a in (workflow.get("agentAttempts") or {}).values() if isinstance(a, dict)]
    if policy not in POLICIES:
        return {"status": "invalid-lifecycle-policy"}
    process_attempts = workflow.get("processAttempts", {})
    pending_processes = [rid for rid, a in process_attempts.items() if not a.get("settledAt") or not a.get("receiptSha256")]
    for rid, run in workflow.get("runs", {}).items():
        if run.get("runnerType") == "claude_process" and rid not in process_attempts:
            pending_processes.append(rid)
    if pending_processes:
        return {"status": "pending-process-exit", "runIds": pending_processes}
    if policy == "process-exit":
        if attempts or any(r.get("runnerType") != "claude_process" for r in workflow.get("runs", {}).values()):
            return {"status": "invalid-lifecycle-policy", "reason": "process-exit does not certify Codex child closure"}
        workflow["lifecycleSummary"] = {"policy": policy, "settled": len(process_attempts), "pending": 0,
            "message": "Original process exit and process-group cleanup recorded; no Codex child was created."}
        return None
    if policy == "strict-close":
        workflow.pop("lifecycleSummary", None)
        pending = [a["agentId"] for a in attempts if a.get("closeStatus") != "closed"]
        return {"status": "pending-agent-close", "reason": "every spawned Codex child must be closed and recorded",
                "openAgentIds": pending} if pending else None
    if profile.get("schemaVersion") != 1 or profile.get("closeSupported") is not False:
        return {"status": "invalid-lifecycle-policy"}
    for run_id, run in (workflow.get("runs") or {}).items():
        if run.get("runnerType") == "claude_process":
            continue
        matches = [a for a in attempts if a.get("runId") == run_id]
        if not run.get("codexThreadId") or len(matches) != 1:
            return {"status": "pending-agent-terminal", "reason": "every run needs one exact child attempt", "runId": run_id}
    pending = []
    for attempt in attempts:
        evidence = attempt.get("executionEvidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        if (not attempt.get("settledAt") or evidence.get("runId") != attempt.get("runId")
                or evidence.get("taskId") != attempt.get("taskId")
                or attempt.get("closeStatus") not in ("unsupported", "closed")):
            pending.append(attempt["agentId"])
    workflow["lifecycleSummary"] = {"policy": policy, "settled": len(attempts) - len(pending),
        "pending": len(pending), "threadCloseUnsupported": [a["agentId"] for a in attempts if a.get("closeStatus") != "closed"],
        "message": lifecycle_notice(workflow)}
    return {"status": "pending-agent-terminal", "pendingAgentIds": pending} if pending else None


def record_agent_terminal(root: Path, workflow_id: str, task_id: str, agent_id: str, transcript: Path) -> Path:
    from .workflow import update_workflow_acceptance, workflow_lock_path, workflow_path
    path = workflow_path(root, workflow_id)
    lock = acquire_file_lock(workflow_lock_path(root, workflow_id), timeout_seconds=30,
                             poll_seconds=0.05, message=lambda: f"Terminal evidence locked: {path}")
    try:
        workflow = load_json(path)
        if (workflow.get("lifecyclePolicy") or {}).get("policy") != "terminal-evidence":
            raise DelegateError("Configure terminal-evidence explicitly before recording execution settlement")
        attempts = workflow.get("agentAttempts") or {}
        candidates = [a for a in attempts.values() if a.get("agentId") == agent_id or a.get("codexThreadId") == agent_id]
        if len(candidates) != 1 or candidates[0].get("taskId") != task_id:
            raise DelegateError("Terminal evidence must bind to one exact task and agent attempt")
        attempt = candidates[0]
        evidence = execution_evidence(root, workflow, attempt, transcript)
        if attempt.get("executionEvidence"):
            if attempt["executionEvidence"] != evidence:
                raise DelegateError("Settled attempt evidence changed; investigate rather than overwriting history")
            return path
        attempt["executionEvidence"] = evidence
        attempt["executionStatus"] = "interrupted" if evidence["host"]["event"] == "turn_aborted" else evidence["runnerStatus"]
        attempt["settledAt"] = now_iso()
        if attempt.get("closeStatus") != "closed":
            attempt["closeStatus"] = "unsupported"
        workflow["revision"] = int(workflow.get("revision") or 0) + 1
        update_workflow_acceptance(workflow)
        write_json(path, workflow)
        return path
    finally:
        lock.release()


def verify_lifecycle_evidence(root: Path, workflow: dict[str, Any]) -> None:
    from .process_run import verify_process
    for rid in workflow.get("processAttempts", {}):
        verify_process(root, rid, load_json(root / f"config_{rid}.json"), load_json(root / f"status_{rid}.json"))
    profile = workflow.get("lifecyclePolicy") or {"policy": "strict-close"}
    if not isinstance(profile, dict):
        raise DelegateError("Invalid lifecycle policy")
    if profile.get("policy") == "process-exit":
        expected = capability_profile(profile, "process-exit")
        if any(profile.get(key) != value for key, value in expected.items()):
            raise DelegateError("Process lifecycle capability profile is inconsistent")
        return
    if profile.get("policy") != "terminal-evidence":
        return
    expected = capability_profile(profile, "terminal-evidence")
    if any(profile.get(key) != value for key, value in expected.items()):
        raise DelegateError("Lifecycle capability profile is inconsistent")
    for attempt in (workflow.get("agentAttempts") or {}).values():
        evidence = attempt.get("executionEvidence")
        if not isinstance(evidence, dict):
            raise DelegateError(f"Missing terminal proof for agent {attempt.get('agentId')}")
        actual = execution_evidence(root, workflow, attempt, Path(str((evidence.get("host") or {}).get("path") or "")))
        if actual != evidence:
            raise DelegateError(f"Terminal evidence changed for agent {attempt.get('agentId')}; cannot accept")


def audit_lifecycle(root: Path, workflow_id: str) -> dict[str, Any]:
    """Read-only eligibility audit; never recover statuses or change old reports."""
    from .workflow import workflow_path
    workflow = load_json(workflow_path(root, workflow_id))
    if workflow.get("workflowId") != workflow_id:
        raise DelegateError("Workflow id mismatch")
    results = []
    for attempt in (workflow.get("agentAttempts") or {}).values():
        item = {key: attempt.get(key) for key in ("agentId", "taskId", "runId", "codexThreadId")}
        item["eligible"] = False
        try:
            thread_id = str(uuid.UUID(str(attempt.get("codexThreadId") or attempt.get("agentId"))))
            matches = list(sessions_root().rglob(f"rollout-*-{thread_id}.jsonl"))
            if len(matches) != 1:
                raise DelegateError("Expected exactly one original host rollout for the native thread id")
            item["transcriptPath"] = str(matches[0])
            evidence = execution_evidence(root, workflow, attempt, matches[0])
            item.update(eligible=True, runnerStatus=evidence["runnerStatus"],
                        hostEvent=evidence["host"]["event"], closeStatus="unsupported",
                        message="执行已结束；宿主不提供线程关闭接口。")
        except (DelegateError, OSError, ValueError, TypeError) as exc:
            item["reason"] = str(exc)
        results.append(item)
    return {"workflowId": workflow_id, "lifecyclePolicy": workflow.get("lifecyclePolicy"),
            "readOnly": True, "attempts": results}
