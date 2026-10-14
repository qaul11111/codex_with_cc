"""Bind opaque desktop deliveries through original parent dispatch records.

No decryption or model-authored report is used as dispatch evidence. The parent
must have received the exact prepared plan, dispatched its unique task handle,
and received that handle back. Its opaque message must match the child's host
delivery byte for byte. This proves plan/dispatch identity, not task compliance.
As with other rollout evidence, this is not an attestation against a malicious
same-user process that can rewrite all local files.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

from .common import DelegateError, same_path
from .lifecycle import MAX_LINE_BYTES, MAX_ROLLOUT_BYTES, sessions_root, timestamp


def record_digest(record: dict) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()


def original_records(path: Path) -> list[dict]:
    """Read a bounded original snapshot; the parent's later turns may append."""
    if path.is_symlink() or not path.resolve().is_relative_to(sessions_root()) or not path.is_file():
        raise DelegateError("Dispatch evidence must use an original regular sessions file")
    info = path.stat()
    if info.st_size > MAX_ROLLOUT_BYTES or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise DelegateError("Dispatch rollout has unsafe size or permissions")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise DelegateError("Dispatch rollout has an unexpected owner")
    records, size = [], 0
    with path.open("rb") as handle:
        while raw := handle.readline(MAX_LINE_BYTES + 1):
            size += len(raw)
            if size > MAX_ROLLOUT_BYTES or len(raw) > MAX_LINE_BYTES or not raw.endswith(b"\n"):
                raise DelegateError("Dispatch rollout is oversized or incomplete")
            try:
                record = json.loads(raw)
            except (ValueError, UnicodeError) as exc:
                raise DelegateError("Malformed dispatch rollout") from exc
            if not isinstance(record, dict):
                raise DelegateError("Malformed dispatch rollout object")
            records.append(record)
    return records


def prepared_outputs(value, depth=0):
    """Unwrap exec's text blocks and successful shell outputs, never arbitrary text."""
    if depth > 6:
        return
    if isinstance(value, str):
        try:
            yield from prepared_outputs(json.loads(value), depth + 1)
        except ValueError:
            return
    elif isinstance(value, list):
        for block in value:
            if isinstance(block, dict) and block.get("type") in ("input_text", "text"):
                yield from prepared_outputs(block.get("text"), depth + 1)
    elif isinstance(value, dict):
        if isinstance(value.get("spawn"), dict) and isinstance(value.get("planFile"), str):
            yield value
        elif value.get("exit_code") == 0:
            yield from prepared_outputs(value.get("output"), depth + 1)


def verify_agent_delivery(path: Path, plan_path: Path, delivery: dict, turn_id: str | None) -> dict:
    from .host_evidence import session_metadata
    from .routing import verified_plan

    plan, workflow = verified_plan(plan_path.resolve())
    meta = session_metadata(path)
    source = meta.get("source") or {}
    spawn = ((source.get("subagent") or {}).get("thread_spawn") or {}) if isinstance(source, dict) else {}
    agent, parent_id = spawn.get("agent_path"), spawn.get("parent_thread_id")
    payload = delivery["payload"]
    if not isinstance(agent, str) or not agent.startswith("/root/") or not parent_id:
        raise DelegateError("Agent instruction lacks child provenance")
    parent_agent = agent.rsplit("/", 1)[0]
    if (payload.get("author") != parent_agent or payload.get("recipient") != agent
            or payload.get("internal_chat_message_metadata_passthrough", {}).get("turn_id") != turn_id
            or not same_path(meta.get("cwd", ""), plan["projectRoot"])
            or meta.get("parent_thread_id") not in (None, parent_id)):
        raise DelegateError("Agent instruction sender, recipient, project or turn mismatch")
    content = payload.get("content")
    envelope = f"Message Type: NEW_TASK\nTask name: {agent}\nSender: {parent_agent}\nPayload:\n"
    if (not isinstance(content, list) or not content or not isinstance(content[0], dict) or content[0].get("type") != "input_text"
            or not isinstance(content[0].get("text"), str) or not content[0]["text"].startswith(envelope)):
        raise DelegateError("Agent instruction is not a current parent NEW_TASK delivery")
    marker = f"WorkflowPlan: {plan_path.resolve()}"
    encrypted = [x.get("encrypted_content") for x in content if isinstance(x, dict) and x.get("type") == "encrypted_content"]
    if not encrypted:
        text = "\n".join(x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "input_text")
        if marker not in [x.strip() for x in text.removeprefix(envelope).splitlines()]:
            raise DelegateError("Original child instruction is not bound to this prepared plan")
        return {"schemaVersion": 1, "source": "original-agent-instruction", "turnId": turn_id,
                "deliverySha256": record_digest(delivery)}
    if (len(content) != 2 or content[0]["text"] != envelope or len(encrypted) != 1
            or not isinstance(encrypted[0], str) or not encrypted[0]):
        raise DelegateError("Ambiguous encrypted agent instruction")

    # Encryption hides the marker. Bind the uniquely generated handle to the
    # registered full plan and its original spawn-producing output before dispatch.
    # Adaptive plans only produce a spawn payload after atomic admission.
    producer = "admit-task" if workflow.get("executionPolicy", {}).get("dispatch") else "prepare-task"
    task_name = plan["taskId"].replace("-", "_") + "_" + plan["planId"][:8]
    if agent != parent_agent + "/" + task_name:
        raise DelegateError("Encrypted instruction task handle does not match the prepared plan")
    collisions = [key for key, p in workflow.get("preparedTasks", {}).items()
                  if p.get("taskId", "").replace("-", "_") + "_" + key[:8] == task_name]
    if collisions != [plan["planId"]]:
        raise DelegateError("Encrypted instruction has an ambiguous prepared task handle")
    paths = list(sessions_root().rglob(f"*{parent_id}.jsonl"))
    if len(paths) != 1:
        raise DelegateError("Cannot uniquely locate original dispatch parent")
    records = original_records(paths[0])
    headers = [r for r in records if r.get("type") == "session_meta"]
    if (len(headers) != 1 or headers[0]["payload"].get("id") != parent_id
            or not same_path(headers[0]["payload"].get("cwd", ""), plan["projectRoot"])
            or (workflow.get("mainUsageBaseline") or {}).get("threadId", parent_id) != parent_id):
        raise DelegateError("Dispatch parent identity or project mismatch")

    expected = {"task_name": task_name, "fork_turns": "none", "model": plan["model"],
                "reasoning_effort": plan["reasoningEffort"]}
    candidates, preparations, calls, outputs = [], [], {}, {}
    for index, record in enumerate(records):
        p = record.get("payload") or {}
        if record.get("type") != "response_item":
            continue
        if p.get("type") in ("function_call", "custom_tool_call"):
            calls.setdefault(p.get("call_id"), []).append((index, record))
            if p.get("type") != "function_call" or not (p.get("name") == "collaboration.spawn_agent"
                    or (p.get("name") == "spawn_agent" and p.get("namespace") == "collaboration")):
                continue
            try:
                args = json.loads(p.get("arguments", ""))
            except (TypeError, ValueError):
                continue
            if isinstance(args, dict) and args.get("task_name") == task_name:
                candidates.append((index, record, args))
        if p.get("type") in ("function_call_output", "custom_tool_call_output"):
            outputs.setdefault(p.get("call_id"), []).append((index, record))
            for result in prepared_outputs(p.get("output")):
                if result.get("planFile") == str(plan_path.resolve()):
                    preparations.append((index, record, result))
    if len(candidates) != 1:
        raise DelegateError("Encrypted instruction requires one original parent spawn")
    spawn_index, spawn_record, args = candidates[0]
    call_id = spawn_record["payload"].get("call_id")
    if not call_id or len(calls.get(call_id, [])) != 1 or len(outputs.get(call_id, [])) != 1:
        raise DelegateError("Original dispatch call/result binding is ambiguous")
    result_index, result_record = outputs[call_id][0]
    try:
        result = json.loads(result_record["payload"].get("output", ""))
    except (TypeError, ValueError) as exc:
        raise DelegateError("Original dispatch result is not readable") from exc
    if (not isinstance(result, dict) or result.get("task_name") != agent
            or result_index <= spawn_index or any(args.get(k) != v for k, v in expected.items())
            or args.get("message") != encrypted[0]):
        raise DelegateError("Original dispatch does not match the encrypted child delivery")
    valid_preparations = []
    for index, record, result in preparations:
        prepared = result["spawn"]
        origin = calls.get(record["payload"].get("call_id"), [])
        if len(origin) != 1 or origin[0][0] >= index:
            continue
        call = origin[0][1]["payload"]
        command = call.get("input", call.get("arguments", ""))
        is_producer = producer in command or (producer == "admit-task"
            and re.search(r"(?<![\w-])prepare-task(?![\w-])", command)
            and re.search(r"(?<![\w-])-Admit(?![\w-])", command))
        if (index < spawn_index and is_producer
                and any(call.get("name") == name for name in ("exec", "exec_command", "functions.exec", "functions.exec_command"))
                and all(prepared.get(k) == v for k, v in expected.items())
                and marker in [x.strip() for x in str(prepared.get("message", "")).splitlines()]
                and timestamp(plan["createdAt"]) <= timestamp(record.get("timestamp"))
                <= timestamp(spawn_record.get("timestamp")) <= timestamp(delivery.get("timestamp"))):
            valid_preparations.append((origin[0][1], record))
    if len(valid_preparations) != 1:
        raise DelegateError("Encrypted instruction lacks unambiguous original plan preparation evidence")
    prepare_call, prepare_result = valid_preparations[0]
    return {"schemaVersion": 1, "source": "original-parent-encrypted-dispatch", "turnId": turn_id,
            "parentPath": str(paths[0].resolve()), "parentThreadId": parent_id,
            "parentMetadataSha256": record_digest(headers[0]), "deliverySha256": record_digest(delivery),
            "prepareCallSha256": record_digest(prepare_call), "prepareResultSha256": record_digest(prepare_result),
            "spawnCallId": call_id, "spawnSha256": record_digest(spawn_record),
            "spawnResultSha256": record_digest(result_record)}
