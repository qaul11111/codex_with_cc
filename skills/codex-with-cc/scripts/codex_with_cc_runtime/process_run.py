"""A real isolated Claude process, launched by main without a model carrier.

Receipts are local audit evidence, not attestations against a malicious same-user
process. No child/thread identity is invented. Timeout kills the process group;
manual cancellation of an already detached process is deliberately unsupported.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .common import ARTIFACT_SCHEMA_VERSION, INVOCATION_CONTRACT, DelegateError, now_iso
from .host_evidence import verify_main_identity
from .io_utils import load_json, write_json
from .lifecycle import digest
from .locks import acquire_file_lock
from .process_permissions import allowed_commands, provider_snapshot, verify_command_pins


def prepare_process(plan: dict, ns) -> None:
    if ns.bypass_permissions:
        raise DelegateError("claude-process forbids permission bypass")
    if any(os.environ.get(k, "").lower() not in ("", "0", "false") for k in ("CLAUDE_CODE_SAFE_MODE", "CLAUDE_CODE_SIMPLE")):
        raise DelegateError("Claude modes that disable hooks cannot execute prepared permissions")
    if not plan["executionPolicy"].get("dispatch"):
        raise DelegateError("claude-process requires MaxParallel and explicit admission")
    identity = verify_main_identity(os.environ.get("CODEX_THREAD_ID", ""), plan["projectRoot"])
    executable = shutil.which("claude")
    if not executable:
        raise DelegateError("Claude CLI is unavailable")
    plan.update(mainHost=identity, model=None, reasoningEffort=None, hostEffortRequired=False,
                allowedCommands=allowed_commands(ns.allowed_commands_file, Path(plan["projectRoot"])),
                executionTimeoutSeconds=ns.execution_timeout_seconds or 900,
                providerSnapshot=provider_snapshot(Path(plan["projectRoot"])), claudeExecutable=str(Path(executable).resolve()),
                processLifecycle={"policy": "process-exit", "cancellation": "bounded-timeout",
                                  "processGroup": True, "killGraceSeconds": 3, "sessionReuse": False})


def validate_process_launch(directory: Path, *, check_claim=True) -> tuple[dict, dict]:
    from .routing import verified_plan
    from .adaptive import require_current_dependencies
    from .fixed_launcher import check_descriptor_safety, check_paths
    directory = directory.resolve()
    if any(os.environ.get(k, "").lower() not in ("", "0", "false") for k in ("CLAUDE_CODE_SAFE_MODE", "CLAUDE_CODE_SIMPLE")):
        raise DelegateError("Claude modes that disable hooks cannot execute prepared permissions")
    descriptor_path = check_descriptor_safety(directory)
    p, w = verified_plan(directory / "plan.json")
    if p["backend"] != "claude-process" or load_json(descriptor_path) != p.get("launchTemplate"):
        raise DelegateError("Prepared process launch descriptor changed")
    if p["mainHost"]["threadId"] != os.environ.get("CODEX_THREAD_ID"):
        raise DelegateError("Process launcher must run in its original main host")
    if verify_main_identity(p["mainHost"]["threadId"], p["projectRoot"]) != p["mainHost"]:
        raise DelegateError("Original main host provenance changed")
    if provider_snapshot(Path(p["projectRoot"])) != p["providerSnapshot"]:
        raise DelegateError("Claude provider/settings changed since preparation")
    if not p["executionPolicy"].get("dispatch"):
        raise DelegateError("Process launch requires admission")
    if check_claim and ((directory / "claimed").exists() or w["preparedTasks"][p["planId"]].get("runId")):
        raise DelegateError("Prepared process has already been claimed")
    require_current_dependencies(p, w)
    verify_command_pins(p)
    check_paths(p["launchTemplate"])
    return p, w


def run_validate_process_launch(ns) -> int:
    p, _ = validate_process_launch(Path(ns.launch_directory))
    print(json.dumps({"valid": True, "backend": p["backend"], "planId": p["planId"]}))
    return 0


def main_launch_evidence(plan: dict, directory: Path) -> dict:
    from .fixed_launcher import _resolve_codex_home
    path = Path(plan["mainHost"]["path"])
    launcher = str(_resolve_codex_home() / "bin/codex-with-cc-launch")
    found = None
    with path.open("rb") as stream:
        while True:
            offset = stream.tell()
            raw = stream.readline()
            if not raw:
                break
            try:
                item = json.loads(raw)
            except ValueError:
                continue
            payload = item.get("payload") or {}
            if item.get("type") != "response_item" or payload.get("type") not in ("function_call", "custom_tool_call"):
                continue
            if payload.get("name") not in ("exec_command", "functions.exec_command", "functions.exec", "exec"):
                continue
            from .lifecycle import timestamp
            try:
                if timestamp(item.get("timestamp")) < timestamp(plan["createdAt"]):
                    continue
            except DelegateError:
                continue
            text = payload.get("arguments", payload.get("input", ""))
            if not isinstance(text, str):
                continue
            candidates = []
            try:
                obj = json.loads(text)
                if isinstance(obj, dict):
                    candidates.append(obj)
            except ValueError:
                # Original functions.exec source: parse only literal JSON tool
                # objects, never evaluate JavaScript or follow computed commands.
                for match in re.finditer(r"(?:tools\.)?exec_command\s*\(\s*(\{)", text):
                    try:
                        obj, _ = json.JSONDecoder().raw_decode(text[match.start(1):])
                        candidates.append(obj)
                    except ValueError:
                        pass
            if any(c.get("cmd") == launcher and c.get("workdir") == str(directory) for c in candidates):
                found = {"status": "original-main-tool-call", "path": str(path), "offset": offset,
                         "length": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "callId": payload.get("call_id")}
    if found is None:
        return {"status": "unavailable", "reason": "Host has not exposed a literal launch call in the original main transcript"}
    return found


def verify_launch_evidence(evidence: dict) -> None:
    if evidence.get("status") == "unavailable":
        return
    if evidence.get("status") != "original-main-tool-call":
        raise DelegateError("Invalid main process launch evidence")
    with Path(evidence["path"]).open("rb") as stream:
        stream.seek(evidence["offset"])
        if hashlib.sha256(stream.read(evidence["length"])).hexdigest() != evidence["sha256"]:
            raise DelegateError("Original main process launch evidence changed")


def process_cli(plan: dict, plan_path: Path, session_id: str) -> list[str]:
    from .claude_cli import new_claude_cli_args
    argv = new_claude_cli_args(plan["workerModel"], plan["taskId"], plan["role"], session_id, False,
                               plan.get("maxBudgetUsd"), False, plan["workerEffort"])
    argv[argv.index("--permission-mode") + 1] = "dontAsk"
    hook = Path(__file__).resolve().parents[1] / "process_permission_hook.py"
    settings = {"disableAllHooks": False, "hooks": {"PreToolUse": [{"matcher": "", "hooks": [{"type": "command",
                 "command": shlex.join([sys.executable, str(hook), str(plan_path)]), "timeout": 10}]}]}}
    tools = ["Read", "Glob", "Grep", "Bash"] + (["Edit", "Write"] if plan["role"] == "implementer" else [])
    # CLI exact rules plus the fail-closed task hook: a user settings broad allow
    # cannot widen the guard's exact command or write-scope checks.
    allowed = ["Read", "Glob", "Grep", "StructuredOutput"] + ["Bash(" + c["command"] + ")" for c in plan["allowedCommands"]]
    if plan["role"] == "implementer":
        allowed.extend(["Edit", "Write"])
    argv.extend(["--tools", ",".join(tools), "--allowedTools", *allowed, "--settings", json.dumps(settings),
                 "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands", "--no-chrome"])
    return [plan["claudeExecutable"], *argv]


def parse_stream(path: Path) -> tuple[dict, list[dict]]:
    from .claude_cli import update_stream_capture
    state, denials = {}, []
    with path.open() as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            update_stream_capture(record, state)
            if record.get("type") == "user":
                for block in (record.get("message") or {}).get("content", []):
                    if (isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error")
                            and re.search(r"permission|not authorized|not allowed|PreToolUse.*(?:deny|blocked)", str(block.get("content", "")), re.I)):
                        denials.append({"source": "original-tool-result", "toolUseId": block.get("tool_use_id"),
                                        "reason": str(block.get("content", ""))[:800]})
            if record.get("type") == "result":
                denials.extend(record.get("permission_denials") or [])
                result = record.get("result")
                if isinstance(result, str) and result.strip() and not record.get("structured_output"):
                    state["finalText"] = result
                if record.get("is_error"):
                    state["resultError"] = True
    return state, denials


def _group_gone(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return True
    return False


def _cleanup(proc: subprocess.Popen, grace: int) -> bool:
    if not _group_gone(proc.pid):
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    if not _group_gone(proc.pid):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    proc.wait(timeout=grace)
    return _group_gone(proc.pid)


def run_process(directory: Path) -> int:
    from .fixed_launcher import claim_descriptor
    from .workflow import workflow_path, workflow_lock_path, update_workflow_record, update_workflow_acceptance
    from .native_run import validate_report
    from .packets import run_packet
    p, _ = validate_process_launch(directory)
    plan_path = directory / "plan.json"
    claim_descriptor(directory)
    p, _ = validate_process_launch(directory, check_claim=False)
    root, rid = Path(p["artifactRoot"]), "process_" + uuid.uuid4().hex
    session_id = str(uuid.uuid4())
    output, raw, stderr, prompt = (root / f"{name}_{rid}.{ext}" for name, ext in (("claude", "md"), ("stream", "jsonl"), ("stderr", "log"), ("prompt", "md")))
    cp, sp, receipt_path = (root / f"{name}_{rid}.json" for name in ("config", "status", "receipt"))
    argv = process_cli(p, plan_path, session_id)
    commands = "\n".join("- " + c["command"] for c in p["allowedCommands"]) or "None; Bash is not authorized."
    prompt.write_text(Path(p["taskFile"]).read_text() + "\n\nRuntime authorization\nWorking directory: " + p["projectRoot"] +
        "\nExact authorized Bash commands (do not add cd, shell wrappers, pipes, redirects or extra arguments):\n" + commands +
        "\nUse Read/Glob/Grep for exploration. Stay inside the allowed write scope. Do not edit pinned scripts or runtime artifacts.\nReturn the requested eight-field report as your final response.\n")
    base = {"artifactSchema": ARTIFACT_SCHEMA_VERSION, "invocationContract": INVOCATION_CONTRACT,
            "runId": rid, "workflowId": p["workflowId"], "taskId": p["taskId"], "role": p["role"],
            "runnerType": "claude_process", "dryRun": False, "outputPath": str(output)}
    config = {**base, "executionPolicy": p["executionPolicy"], "repoRoot": p["projectRoot"],
              "preparedPlanId": p["planId"], "planPath": str(plan_path), "planSha256": digest(plan_path),
              "mainHost": p["mainHost"], "mainLaunchEvidence": main_launch_evidence(p, directory),
              "sessionId": session_id, "model": p["workerModel"], "workerEffort": p["workerEffort"],
              "processLifecycle": p["processLifecycle"], "argv": argv, "receiptPath": str(receipt_path),
              "rawStreamPath": str(raw), "stderrPath": str(stderr), "promptPath": str(prompt),
              **{k: p.get(k) for k in ("scope", "tests", "allowParallel", "dependsOn", "reviewForTaskId", "reviewForRunId", "reviewKind", "verifiedImplementerRuns")}}
    write_json(cp, config)
    status = {**base, "status": "starting", "startedAt": now_iso(), "pid": None, "launcherPid": os.getpid()}
    write_json(sp, status)
    lock = acquire_file_lock(workflow_lock_path(root, p["workflowId"]), 30, .05, lambda: "Process registration locked")
    try:
        w = load_json(workflow_path(root, p["workflowId"]))
        w["preparedTasks"][p["planId"]]["runId"] = rid
        w.setdefault("processAttempts", {})[rid] = {"runId": rid, "taskId": p["taskId"], "preparedPlanId": p["planId"],
            "mainHost": p["mainHost"], "startedAt": status["startedAt"], "lifecyclePolicy": "process-exit"}
        write_json(workflow_path(root, p["workflowId"]), w)
    finally:
        lock.release()
    proc, reason, code, clean = None, None, 1, False
    old_handlers = {}
    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)
    if __import__("threading").current_thread() is __import__("threading").main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            old_handlers[sig] = signal.signal(sig, interrupted)
    try:
        env = dict(os.environ)
        env.pop("CODEX_CLAUDE_CHILD_THREAD", None)
        with prompt.open("rb") as stdin, raw.open("xb") as stdout, stderr.open("xb") as err:
            proc = subprocess.Popen(argv, cwd=p["projectRoot"], stdin=stdin, stdout=stdout, stderr=err,
                                    env=env, start_new_session=True)
            status.update(status="running", pid=proc.pid, processGroupId=proc.pid, workerStartedAt=now_iso())
            write_json(sp, status)
            try:
                code = proc.wait(timeout=p["executionTimeoutSeconds"])
            except subprocess.TimeoutExpired:
                reason, code = "execution-timeout", 124
            finally:
                clean = _cleanup(proc, p["processLifecycle"]["killGraceSeconds"])
    except BaseException as exc:
        reason = "launcher-interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "process-launch-error"
        if proc is not None:
            clean = _cleanup(proc, p["processLifecycle"]["killGraceSeconds"])
        else:
            clean = True
        stderr.touch(exist_ok=True)
        with stderr.open("a") as err:
            err.write("\nRuntime exception: " + type(exc).__name__ + ": " + str(exc) + "\n")
    finally:
        for sig, previous in old_handlers.items():
            signal.signal(sig, previous)
    raw.touch(exist_ok=True)
    state, denials = parse_stream(raw)
    text = state.get("finalText", "")
    output.write_text(text)
    report_valid = True
    try:
        validate_report(text, p["role"])
    except DelegateError:
        report_valid = False
    if denials:
        reason = reason or "permission-denied"
    if not clean:
        reason = reason or "process-group-cleanup-unverified"
    completed = code == 0 and reason is None and report_valid and state.get("sawResultSuccess") and not state.get("resultError")
    status.update(status="completed" if completed else "failed", completedAt=now_iso(), exitCode=code,
                  actualProcessExitCode=proc.returncode if proc is not None else None,
                  failureReason=reason or (None if completed else "invalid-or-unsuccessful-worker-result"),
                  processGroupExited=clean, permissionDenials=denials, reportSource="original-claude-stream",
                  models=state.get("models", []), usage=state.get("usage", {}), totalCostUsd=state.get("totalCostUsd"), attemptCount=1)
    write_json(sp, status)
    receipt = {"schemaVersion": 1, "runId": rid, "taskId": p["taskId"], "processPid": status["pid"],
               "sessionId": session_id, "startedAt": status["startedAt"], "completedAt": status["completedAt"],
               "exitCode": code, "actualProcessExitCode": status["actualProcessExitCode"], "processGroupExited": clean,
               "mainHost": p["mainHost"], "mainLaunchEvidence": config["mainLaunchEvidence"],
               "files": {str(f): digest(f) for f in (cp, sp, output, raw, stderr, prompt, plan_path)},
               "evidenceLimit": "Local original process artifacts; not a billing receipt or same-user security attestation"}
    write_json(receipt_path, receipt)
    update_workflow_record(root, p["workflowId"], p["taskId"], p["role"], p["scope"], p["tests"], p["dependsOn"], rid,
        cp, sp, output, prompt, raw, stderr, status["status"], runner_type="claude_process",
        review_for_task_id=p.get("reviewForTaskId"), review_kind=p.get("reviewKind"), review_for_run_id=p.get("reviewForRunId"),
        verified_implementer_runs=p.get("verifiedImplementerRuns"))
    lock = acquire_file_lock(workflow_lock_path(root, p["workflowId"]), 30, .05, lambda: "Process settlement locked")
    try:
        w = load_json(workflow_path(root, p["workflowId"]))
        attempt = w["processAttempts"][rid]
        attempt.update(receiptPath=str(receipt_path), receiptSha256=digest(receipt_path), processPid=status["pid"],
                       executionStatus=status["status"])
        if clean:
            attempt["settledAt"] = now_iso()
        update_workflow_acceptance(w)
        write_json(workflow_path(root, p["workflowId"]), w)
    finally:
        lock.release()
    print(json.dumps({"exitCode": 0 if completed else (code or 1), "runId": rid, "backend": "claude-process",
                      "receiptPath": str(receipt_path), "settled": clean, "packet": run_packet(root, w, rid)}, ensure_ascii=False))
    return 0 if completed else (code or 1)


def verify_process(root: Path, rid: str, config: dict, status: dict) -> dict:
    from .routing import verified_plan
    from .native_run import validate_report
    p, w = verified_plan(Path(config["planPath"]))
    attempt = w.get("processAttempts", {}).get(rid, {})
    if not attempt.get("settledAt") or attempt.get("runId") != rid or attempt.get("preparedPlanId") != p["planId"]:
        raise DelegateError("Process lacks verified settlement")
    rp = Path(config["receiptPath"])
    if str(rp) != attempt.get("receiptPath") or digest(rp) != attempt.get("receiptSha256"):
        raise DelegateError("Process receipt changed")
    receipt = load_json(rp)
    expected_files = {str(root / f"config_{rid}.json"), str(root / f"status_{rid}.json"), config["outputPath"],
                      config["rawStreamPath"], config["stderrPath"], config["promptPath"], config["planPath"]}
    if set(receipt.get("files", {})) != expected_files:
        raise DelegateError("Process receipt artifact bindings are incomplete")
    for name, sha in receipt["files"].items():
        file = Path(name)
        if not file.resolve().is_relative_to(root.resolve()) or file.is_symlink() or digest(file) != sha:
            raise DelegateError("Original process artifact changed")
    if (p["backend"] != "claude-process" or config.get("planSha256") != digest(Path(config["planPath"]))
            or w["preparedTasks"][p["planId"]].get("runId") != rid or p["artifactRoot"] != str(root.resolve())):
        raise DelegateError("Process prepared plan binding mismatch")
    for key, expected in (("runId", rid), ("workflowId", p["workflowId"]), ("taskId", p["taskId"]), ("role", p["role"]),
                          ("runnerType", "claude_process"), ("artifactSchema", ARTIFACT_SCHEMA_VERSION), ("invocationContract", INVOCATION_CONTRACT)):
        if config.get(key) != expected or status.get(key) != expected:
            raise DelegateError("Process config/status identity mismatch")
    if config.get("mainHost") != p["mainHost"] or verify_main_identity(p["mainHost"]["threadId"], p["projectRoot"]) != p["mainHost"]:
        raise DelegateError("Process main host provenance mismatch")
    verify_launch_evidence(config["mainLaunchEvidence"])
    if status.get("status") not in ("completed", "failed") or type(status.get("exitCode")) is not int or not status.get("processGroupExited"):
        raise DelegateError("Process has no original terminal exit evidence")
    if receipt.get("processPid") != status.get("pid") or receipt.get("exitCode") != status.get("exitCode") or not receipt.get("processGroupExited"):
        raise DelegateError("Process exit receipt binding mismatch")
    if status.get("pid") is not None and (type(status["pid"]) is not int or status["pid"] <= 0 or not _group_gone(status["pid"])):
        raise DelegateError("Process group still alive or identity reused")
    if status.get("dryRun") or config.get("dryRun") or status.get("statusRecoveredFromReport"):
        raise DelegateError("Process evidence must be original real execution")
    state, denials = parse_stream(Path(config["rawStreamPath"]))
    text = Path(config["outputPath"]).read_text()
    if text != state.get("finalText", "") or denials != status.get("permissionDenials"):
        raise DelegateError("Process report/permissions differ from original stream")
    if status["status"] == "completed":
        validate_report(text, p["role"])
        if status["exitCode"] != 0 or denials or not state.get("sawResultSuccess") or state.get("resultError"):
            raise DelegateError("Process completion contradicts original stream")
    for key in ("scope", "tests", "allowParallel", "executionPolicy", "dependsOn", "reviewForTaskId", "reviewForRunId", "reviewKind", "verifiedImplementerRuns"):
        if config.get(key) != p.get(key):
            raise DelegateError("Process inputs differ from prepared plan")
    if rid not in w.get("runs", {}) or rid not in w.get("tasks", {}).get(p["taskId"], {}).get("runs", []):
        raise DelegateError("Process run is missing from workflow")
    return {"config": config, "status": status, "workflow": w, "artifactRoot": root}
