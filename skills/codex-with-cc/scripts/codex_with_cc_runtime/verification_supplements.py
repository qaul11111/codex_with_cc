"""Historical verification supplements for superseded DONE delegate reports.

A superseded (not current/latest) completed single-attempt Claude Code delegate
run whose DONE report abbreviated exact declared verification commands can gain
a create-only sidecar that binds each missing command to the exact Bash
tool_use/tool_result pair in the run's original raw stream. History is never
edited: the sidecar adds independently verifiable evidence next to untouched
config/status/report/stream artifacts.

Every acceptance rehashes the original artifacts and re-derives the evidence
from the stream instead of trusting stored booleans. The sidecar is a local
audit record: it is not tamper-proof against a hostile same-user process and it
never replaces a valid current final report.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
from hashlib import sha256
from pathlib import Path
from typing import Any

from .artifacts import declared_test_variants, resolve_artifact_root, verify_artifacts
from .common import DelegateError, boolish, now_iso
from .io_utils import load_json
from .reports import parse_report_final_result, parse_report_status, report_section

SUPPLEMENT_SCHEMA = "codex-with-cc-verification-supplement"
SUPPLEMENT_SCHEMA_VERSION = 1
MAX_STREAM_BYTES = 512 * 1024 * 1024
MAX_LINE_BYTES = 16 * 1024 * 1024
KNOWN_WARNING_LINE = re.compile(r"^\[claude-code:[A-Za-z0-9_]+\]")
SAFE_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
# Allowlisted tool_use_result fields. Anything else (background/pending/timeout/
# task handles, or unknown future shapes) fails closed.
ALLOWED_RESULT_FIELDS = frozenset({"stdout", "stderr", "interrupted", "isImage", "noOutputExpected", "exitCode"})


def _reject_symlink_components(path: Path, description: str) -> None:
    """Walk EVERY component of path without resolving and reject any symlink.

    Mirrors the fixed_launcher.py component-walk pattern: lstat each component
    so dangling symlinks are still detected, and missing components fail
    closed. Relative paths are made absolute against the current directory
    first; an untrusted alias is never silently canonicalized — callers must
    pass the canonical root explicitly.
    """
    candidate = Path(path)
    absolute = candidate if candidate.is_absolute() else Path.cwd() / candidate
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise DelegateError(f"{description}: cannot inspect path component {current}: {exc}") from exc
        if stat.S_ISLNK(mode):
            raise DelegateError(f"{description}: symlink in path component: {current}")


def supplement_path(root: Path | str, run_id: str) -> Path:
    candidate_root = Path(root)
    _reject_symlink_components(candidate_root, "artifact root")
    root = candidate_root.resolve()
    if not run_id or not SAFE_RUN_ID.fullmatch(run_id) or ".." in run_id:
        raise DelegateError(f"Unsafe run id for verification supplement: {run_id!r}")
    # Never resolve the sidecar itself: a symlinked sidecar must stay visible
    # to the is_symlink checks instead of being collapsed to its target.
    path = root / f"verification-supplement_{run_id}.json"
    if path.parent != root:
        raise DelegateError(f"Verification supplement path escapes the artifact root: {run_id!r}")
    return path


def _checked_file(root: Path, path: Path, description: str) -> Path:
    """Reject symlinks in the final component and any in-root ancestor BEFORE resolve."""
    candidate = Path(path)
    if candidate.is_symlink():
        raise DelegateError(f"{description} must be a regular file, not a symlink: {candidate}")
    if candidate.is_absolute():
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            relative = None
        if relative is not None:
            ancestor = root
            for part in relative.parts[:-1]:
                ancestor = ancestor / part
                if ancestor.is_symlink():
                    raise DelegateError(f"{description} contains a symlinked path component: {ancestor}")
    if not candidate.is_file():
        raise DelegateError(f"{description} is missing or not a regular file: {candidate}")
    return candidate


def _sha256(path: Path) -> str:
    hasher = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _resolve_run_context(root: Path, run_id: str) -> dict[str, Any]:
    """Mandatory existing artifact validation plus strict narrow eligibility."""
    root = Path(root)
    config_path = _checked_file(root, root / f"config_{run_id}.json", "delegate config")
    status_path = _checked_file(root, root / f"status_{run_id}.json", "delegate status")
    record = verify_artifacts(run_id, str(root), recover_status=False)
    config, status, workflow = record["config"], record["status"], record["workflow"]
    if str(config.get("runId") or "") != run_id or str(status.get("runId") or "") != run_id:
        raise DelegateError(f"Delegate config/status runId does not match run {run_id}.")
    task_id = str(config.get("taskId"))
    workflow_id = str(config.get("workflowId"))
    task = (workflow.get("tasks") or {}).get(task_id) or {}
    if str(task.get("latestRunId") or "") == run_id:
        raise DelegateError(
            f"Verification supplement only applies to superseded runs; "
            f"run {run_id} is the current report for task {task_id}."
        )
    if str(status.get("status")) != "completed":
        raise DelegateError(f"Verification supplement requires a completed run; actual status: {status.get('status')}")
    report_path = _checked_file(root, Path(str(config.get("outputPath"))), "delegate report")
    report_text = report_path.read_text(encoding="utf-8")
    if parse_report_status(report_text) != "DONE" or parse_report_final_result(report_text) != "DONE":
        raise DelegateError("Verification supplement requires report Status and Final Result DONE.")
    if boolish(config.get("dryRun")) or boolish(status.get("dryRun")):
        raise DelegateError("dry-run runs cannot use verification supplements.")
    attempts = list(status.get("attempts") or [])
    if any(boolish(attempt.get("dryRun")) for attempt in attempts):
        raise DelegateError("dry-run attempts cannot use verification supplements.")
    if (
        boolish(config.get("trustedLocalFallback"))
        or boolish(status.get("trustedLocalFallback"))
        or config.get("artifactRootFallbackReason")
        or status.get("artifactRootFallbackReason")
    ):
        raise DelegateError("fallback-produced runs cannot use verification supplements.")
    if boolish(status.get("statusRecoveredFromReport")):
        raise DelegateError("report-recovered status cannot use verification supplements.")
    if len(attempts) != 1 or int(status.get("retryCount") or 0) != 0:
        raise DelegateError("verification supplements require a single-attempt run.")
    if str(config.get("runnerType") or "") != "claude_code":
        raise DelegateError("verification supplements require runnerType claude_code.")
    recorded_stream = str(config.get("rawStreamPath") or "")
    if not recorded_stream or recorded_stream != str(status.get("rawStreamPath") or ""):
        raise DelegateError("rawStreamPath binding mismatch between config and status.")
    stream_path = Path(recorded_stream)
    if not stream_path.is_absolute():
        raise DelegateError("raw stream path must be absolute.")
    try:
        stream_path.resolve().relative_to(root)
    except ValueError as exc:
        raise DelegateError("raw stream escapes the artifact root.") from exc
    # The stream must be the run's exact expected stream file, not just any
    # file inside the artifact root, and the workflow run entry must agree.
    expected_stream = root / f"stream_{run_id}.jsonl"
    if stream_path != expected_stream:
        raise DelegateError(
            f"raw stream is not the run's exact expected stream path: expected {expected_stream}, recorded {stream_path}."
        )
    run_entry = (workflow.get("runs") or {}).get(run_id) or {}
    if str(run_entry.get("rawStreamPath") or "") != recorded_stream or str(run_entry.get("taskId") or "") != task_id:
        raise DelegateError("raw stream workflow binding mismatch for run.")
    resolved_stream = _checked_file(root, stream_path, "raw stream")
    session_id = str(attempts[0].get("sessionId") or "")
    if not session_id:
        raise DelegateError("run attempt is missing session identity.")
    tests = [str(item).strip() for item in config.get("tests") or [] if str(item).strip()]
    verification_text = report_section(report_text, "Verification")
    missing = [
        item
        for item in tests
        if not any(variant in verification_text for variant in declared_test_variants(item, run_id, task_id))
    ]
    if not missing:
        raise DelegateError("no missing declared tests require a supplement.")
    return {
        "run_id": run_id,
        "task_id": task_id,
        "workflow_id": workflow_id,
        "session_id": session_id,
        "report_path": report_path,
        "stream_path": resolved_stream,
        "missing": missing,
        "hashes": {
            "config": _sha256(config_path),
            "status": _sha256(status_path),
            "report": _sha256(report_path),
            "stream": _sha256(resolved_stream),
        },
    }


def _derive_stream_evidence(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Bind each missing declared command to one exact, successful Bash call."""
    stream_path = context["stream_path"]
    session_id = context["session_id"]
    wanted = {
        command: declared_test_variants(command, context["run_id"], context["task_id"])
        for command in context["missing"]
    }
    uses: dict[str, list[dict[str, Any]]] = {}
    results: dict[str, list[dict[str, Any]]] = {}
    seen_use_ids: set[str] = set()
    content_seen = False
    total_bytes = 0
    line_number = 0
    with stream_path.open("rb") as stream:
        while True:
            raw = stream.readline(MAX_LINE_BYTES + 1)
            if not raw:
                break
            total_bytes += len(raw)
            if total_bytes > MAX_STREAM_BYTES:
                raise DelegateError("raw stream exceeds the bounded parser limit.")
            if len(raw) > MAX_LINE_BYTES:
                raise DelegateError(f"raw stream record exceeds the bounded line limit at line {line_number + 1}.")
            line_number += 1
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise DelegateError(f"Malformed stream record at line {line_number}.") from exc
            stripped = text.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except ValueError as exc:
                # Conservatively allow known leading CLI warning lines only before
                # any conversation content record; anything else fails closed.
                if not content_seen and KNOWN_WARNING_LINE.match(stripped):
                    continue
                raise DelegateError(f"Malformed stream record at line {line_number}.") from exc
            if not isinstance(record, dict):
                raise DelegateError(f"Malformed stream record at line {line_number}.")
            record_type = record.get("type")
            if record_type not in ("assistant", "user"):
                continue
            content_seen = True
            message = record.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                raise DelegateError(f"Malformed stream content at line {line_number}.")
            record_session = record.get("session_id")
            record_uuid = record.get("uuid")
            if record_session is not None and not isinstance(record_session, str):
                raise DelegateError(f"Malformed stream metadata at line {line_number}.")
            if record_uuid is not None and not isinstance(record_uuid, str):
                raise DelegateError(f"Malformed stream metadata at line {line_number}.")
            if record_type == "assistant":
                for block in content:
                    if not isinstance(block, dict):
                        raise DelegateError(f"Malformed stream content at line {line_number}.")
                    if block.get("type") != "tool_use":
                        continue
                    use_id = block.get("id")
                    if not isinstance(use_id, str) or not use_id:
                        raise DelegateError(f"Malformed tool_use record at line {line_number}.")
                    if use_id in seen_use_ids:
                        raise DelegateError(f"duplicate tool_use id in stream: {use_id}")
                    seen_use_ids.add(use_id)
                    if block.get("name") != "Bash":
                        continue
                    tool_input = block.get("input")
                    command = tool_input.get("command") if isinstance(tool_input, dict) else None
                    if not isinstance(command, str):
                        raise DelegateError(f"Malformed Bash tool_use record at line {line_number}.")
                    for declared, variants in wanted.items():
                        if command in variants:
                            uses.setdefault(declared, []).append(
                                {"toolUseId": use_id, "line": line_number, "uuid": record_uuid, "session": record_session}
                            )
            else:
                tool_result_blocks = [
                    block
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "tool_result"
                ]
                for block in content:
                    if not isinstance(block, dict):
                        raise DelegateError(f"Malformed stream content at line {line_number}.")
                    if block.get("type") != "tool_result":
                        continue
                    use_id = block.get("tool_use_id")
                    if not isinstance(use_id, str) or not use_id:
                        raise DelegateError(f"Malformed tool_result record at line {line_number}.")
                    results.setdefault(use_id, []).append(
                        {
                            "line": line_number,
                            "uuid": record_uuid,
                            "session": record_session,
                            "is_error": block.get("is_error"),
                            # A record-level tool_use_result cannot be safely
                            # attributed when one record carries several results.
                            "shared_record": len(tool_result_blocks) > 1,
                            "tool_use_result": record.get("tool_use_result"),
                        }
                    )
    evidence: list[dict[str, Any]] = []
    for declared in context["missing"]:
        matches = uses.get(declared) or []
        if not matches:
            raise DelegateError(f"no stream evidence for declared command: {declared}")
        if len(matches) > 1:
            raise DelegateError(f"ambiguous stream evidence for declared command: {declared}")
        use = matches[0]
        if use["session"] != session_id:
            raise DelegateError(f"stream evidence session mismatch for declared command: {declared}")
        found = results.get(use["toolUseId"]) or []
        if not found:
            raise DelegateError(f"missing tool_result for tool_use {use['toolUseId']}.")
        if len(found) > 1:
            raise DelegateError(f"duplicate tool_result for tool_use {use['toolUseId']}.")
        result = found[0]
        if result["shared_record"]:
            raise DelegateError(
                f"ambiguous tool_use_result attribution for tool_use {use['toolUseId']}: "
                "the user record carries multiple tool_result blocks."
            )
        if result["line"] <= use["line"]:
            raise DelegateError(f"tool_result appears before its tool_use for {use['toolUseId']} (reordered stream).")
        if result["session"] != session_id:
            raise DelegateError(f"stream evidence session mismatch for declared command: {declared}")
        if result["is_error"] is not False:
            raise DelegateError(f"tool_result is_error must be explicitly false for {use['toolUseId']}.")
        tool_use_result = result["tool_use_result"]
        if not isinstance(tool_use_result, dict):
            raise DelegateError(f"tool_use_result must be a structured object for {use['toolUseId']}.")
        unknown = sorted(set(tool_use_result) - ALLOWED_RESULT_FIELDS)
        if unknown:
            raise DelegateError(
                f"unsupported tool_use_result fields for {use['toolUseId']}: {unknown} "
                "(possible background/pending/timeout/task handle)."
            )
        if tool_use_result.get("interrupted") is not False:
            raise DelegateError(f"tool_use_result interrupted must be explicitly false for {use['toolUseId']}.")
        exit_code = tool_use_result.get("exitCode")
        if exit_code is not None and (type(exit_code) is not int or exit_code != 0):
            raise DelegateError(f"tool_use_result exitCode must be zero when present for {use['toolUseId']}.")
        evidence.append(
            {
                "command": declared,
                "toolUseId": use["toolUseId"],
                "use": {"line": use["line"], "uuid": use["uuid"]},
                "result": {"line": result["line"], "uuid": result["uuid"]},
                "exitCode": exit_code,
                # A bare Claude tool result without exitCode proves only
                # tool-reported success; never invent a numeric exit 0 for it.
                "evidence": "exit-code-0" if exit_code == 0 else "tool-reported-success",
            }
        )
    return evidence


def _build_sidecar(context: dict[str, Any], evidence: list[dict[str, Any]], recorded_at: str | None) -> dict[str, Any]:
    return {
        "schema": SUPPLEMENT_SCHEMA,
        "schemaVersion": SUPPLEMENT_SCHEMA_VERSION,
        "runId": context["run_id"],
        "taskId": context["task_id"],
        "workflowId": context["workflow_id"],
        "sessionId": context["session_id"],
        "rawStreamPath": str(context["stream_path"]),
        "commands": evidence,
        "sha256": context["hashes"],
        "recordedAt": recorded_at,
    }


def load_and_verify_supplement(root: Path | str, run_id: str) -> list[str]:
    """Strictly re-verify a sidecar against the untouched originals."""
    path = supplement_path(root, run_id)
    if path.is_symlink() or not path.is_file():
        raise DelegateError(f"verification supplement sidecar must be a regular file, not a symlink: {path}")
    root = path.parent
    context = _resolve_run_context(root, run_id)
    evidence = _derive_stream_evidence(context)
    expected = _build_sidecar(context, evidence, recorded_at=None)
    try:
        stored = load_json(path)
    except (ValueError, OSError) as exc:
        raise DelegateError(f"verification supplement sidecar is unreadable: {path}") from exc
    if not isinstance(stored, dict):
        raise DelegateError(f"verification supplement sidecar is malformed: {path}")
    recorded_at = stored.get("recordedAt")
    if not isinstance(recorded_at, str) or not recorded_at.strip():
        raise DelegateError("verification supplement sidecar is missing recordedAt.")
    comparable = {key: value for key, value in stored.items() if key != "recordedAt"}
    expected_comparable = {key: value for key, value in expected.items() if key != "recordedAt"}
    if comparable != expected_comparable:
        raise DelegateError("verification supplement sidecar does not match re-derived evidence.")
    return [str(item["command"]) for item in stored["commands"]]


def existing_sidecar_coverage(root: Path | str, run_id: str, record: dict[str, Any]) -> list[str] | None:
    """Gate hook: covered commands when a valid sidecar exists; None when absent.

    No sidecar returns None so the historical gate fails unchanged; an existing
    but invalid or now-inapplicable sidecar raises instead of being silently
    ignored, even when the run's report is current, non-DONE, or fully reported.
    """
    path = supplement_path(root, run_id)
    if not os.path.lexists(path):
        return None
    task_id = str((record.get("config") or {}).get("taskId") or "")
    try:
        return load_and_verify_supplement(root, run_id)
    except DelegateError as exc:
        raise DelegateError(f"Verification supplement invalid for RunId {run_id} TaskId {task_id}: {exc}") from exc


def record_verification_supplement(run_id: str, artifact_root_value: str | None) -> Path:
    """Create-only sidecar write; never overwrites and never edits history.

    A repeated call verifies the existing evidence against re-derived data and
    returns without rewriting; a diverging existing sidecar fails safe.
    """
    if artifact_root_value:
        # Reject alias roots BEFORE resolve_artifact_root canonicalizes them.
        _reject_symlink_components(Path(str(artifact_root_value)), "artifact root")
    root = resolve_artifact_root(artifact_root_value, run_id=run_id)
    path = supplement_path(root, run_id)
    context = _resolve_run_context(root, run_id)
    evidence = _derive_stream_evidence(context)
    sidecar = _build_sidecar(context, evidence, recorded_at=now_iso())
    payload = json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n"
    if os.path.lexists(path):
        load_and_verify_supplement(root, run_id)
        return path
    try:
        with path.open("xb") as handle:
            handle.write(payload.encode("utf-8"))
    except FileExistsError:
        load_and_verify_supplement(root, run_id)
    return path


def run_record_verification_supplement(ns: argparse.Namespace) -> int:
    root = resolve_artifact_root(ns.artifact_root, run_id=ns.run_id)
    existed = os.path.lexists(supplement_path(root, ns.run_id))
    path = record_verification_supplement(ns.run_id, ns.artifact_root)
    if existed:
        print(f"Verification supplement already present and verified: {path}")
    else:
        print(f"Verification supplement recorded: {path}")
    return 0
