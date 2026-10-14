"""Read original local Codex provenance; never synthesize host events."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .common import DelegateError, same_path
from .lifecycle import sessions_root


def session_metadata(path: Path) -> dict:
    if not path.resolve().is_relative_to(sessions_root().resolve()):
        raise DelegateError("Host transcript must come from the original sessions directory")
    with path.open() as handle:
        for line in handle:
            r = json.loads(line)
            if r.get("type") == "session_meta":
                return r["payload"]
    raise DelegateError("Host session metadata is missing")


def verify_main_identity(thread_id: str, project: str) -> dict:
    paths = list(sessions_root().rglob(f"*{thread_id}.jsonl"))
    if len(paths) != 1:
        raise DelegateError("Cannot uniquely locate original main-thread session")
    meta = session_metadata(paths[0])
    source = meta.get("source")
    if meta.get("id") != thread_id or not same_path(meta.get("cwd", ""), project):
        raise DelegateError("Main-thread session project/identity mismatch")
    if (isinstance(source, dict) and source.get("subagent")) or meta.get("parent_thread_id") or meta.get("thread_source") == "subagent":
        raise DelegateError("A subagent cannot record main-thread acceptance")
    return {"threadId": thread_id, "path": str(paths[0].resolve()),
            "metadataSha256": hashlib.sha256(json.dumps(meta, sort_keys=True).encode()).hexdigest()}


def final_response(path: Path) -> tuple[str, str | None]:
    final, model = "", None
    turn_id = None
    responses = []
    with path.open() as handle:
        for line in handle:
            r = json.loads(line)
            p = r.get("payload") or {}
            if r.get("type") == "event_msg" and p.get("type") == "task_started":
                final, model = "", None
                turn_id = p.get("turn_id")
                responses = []
            if r.get("type") == "turn_context":
                model = p.get("model", model)
            if r.get("type") == "response_item":
                responses.append(p)
    # Some desktop providers label model responses with their own turn ID. Bind
    # that ID through an original tool call and the host's matching result in this
    # task turn; never accept an arbitrary mismatched final-response ID.
    calls, results = {}, {}
    for index, p in enumerate(responses):
        kind, call_id = p.get("type"), p.get("call_id")
        if call_id and kind in ("function_call", "custom_tool_call"):
            calls.setdefault(call_id, []).append((index, p))
        elif call_id and kind in ("function_call_output", "custom_tool_call_output"):
            results.setdefault(call_id, []).append((index, p))
    response_turns = {turn_id: -1}
    for call_id, items in calls.items():
        outputs = results.get(call_id, [])
        if len(items) != 1 or len(outputs) != 1:
            continue
        (call_index, call), (result_index, result) = items[0], outputs[0]
        provider_turn = (call.get("internal_chat_message_metadata_passthrough") or {}).get("turn_id")
        host_turn = (result.get("internal_chat_message_metadata_passthrough") or {}).get("turn_id")
        if (isinstance(provider_turn, str) and provider_turn and turn_id and host_turn == turn_id
                and call_index < result_index and result["type"] == call["type"] + "_output"):
            response_turns[provider_turn] = min(response_turns.get(provider_turn, result_index), result_index)
    # Keep the original explicit final, never task_complete.last_agent_message,
    # which can be a shortened or reformatted summary.
    for index, p in enumerate(responses):
        response_turn = (p.get("internal_chat_message_metadata_passthrough") or {}).get("turn_id", turn_id)
        if (p.get("type") == "message" and p.get("role") == "assistant"
                and (p.get("channel") == "final" or p.get("phase") == "final_answer")
                and p.get("channel") in (None, "final") and p.get("phase") in (None, "final_answer")
                and response_turn in response_turns and response_turns[response_turn] < index):
            final = "\n".join(str(x.get("text", "")) for x in p.get("content", []) if x.get("type") in ("output_text", "text"))
    if not final:
        raise DelegateError("Native worker has no final response in the terminal host turn")
    return final, model


def verify_plan_prompt(path: Path, plan_path: Path) -> dict:
    """Bind the current turn's instruction, including encrypted desktop delivery."""
    last_user = ""
    delivery = None
    turn_id = None
    with path.open() as handle:
        for line in handle:
            r = json.loads(line)
            p = r.get("payload") or {}
            if r.get("type") == "event_msg" and p.get("type") == "task_started":
                last_user, delivery, turn_id = "", None, p.get("turn_id")
            if r.get("type") == "event_msg" and p.get("type") == "user_message" and isinstance(p.get("message"), str):
                last_user = p["message"]
                delivery = None
            if r.get("type") == "response_item" and p.get("type") == "message" and p.get("role") == "user":
                content = p.get("content", [])
                last_user = content if isinstance(content, str) else "\n".join(x.get("text", "") for x in content if isinstance(x, dict))
                delivery = None
            if r.get("type") == "response_item" and p.get("type") == "agent_message":
                content = p.get("content")
                if (isinstance(content, list) and content and isinstance(content[0], dict)
                        and content[0].get("type") == "input_text"
                        and str(content[0].get("text", "")).startswith("Message Type: MESSAGE\n")):
                    # In-turn coordination does not dispatch a new task and cannot
                    # supply its binding. task_started clears prior-turn dispatch.
                    continue
                if delivery is not None:
                    raise DelegateError("Multiple task instructions in one host turn are ambiguous")
                last_user, delivery = "", r
    if delivery is not None:
        from .dispatch_evidence import verify_agent_delivery
        return verify_agent_delivery(path, plan_path, delivery, turn_id)
    marker = f"WorkflowPlan: {plan_path.resolve()}"
    if marker not in [line.strip() for line in last_user.splitlines()]:
        raise DelegateError("Original child instruction is not bound to this prepared plan")
    return {"schemaVersion": 1, "source": "original-user-instruction", "turnId": turn_id,
            "instructionSha256": hashlib.sha256(last_user.encode()).hexdigest()}


def verify_active_child(thread_id: str, project: str, model: str, plan_path: Path) -> None:
    paths = list(sessions_root().rglob(f"*{thread_id}.jsonl")) if thread_id else []
    if len(paths) != 1:
        raise DelegateError("Cannot uniquely locate the original carrier session")
    meta = session_metadata(paths[0])
    source = meta.get("source") or {}
    spawn = ((source.get("subagent") or {}).get("thread_spawn") or {}) if isinstance(source, dict) else {}
    if meta.get("id") != thread_id or not spawn.get("parent_thread_id") or not same_path(meta.get("cwd", ""), project):
        raise DelegateError("Prepared launcher requires a real child in the configured project")
    actual_model = None
    with paths[0].open() as handle:
        for line in handle:
            r = json.loads(line)
            if r.get("type") == "turn_context":
                actual_model = r["payload"].get("model", actual_model)
    if actual_model != model:
        raise DelegateError("Carrier host model does not match the prepared task")
    from .io_utils import load_json
    verify_requested_effort(paths[0], load_json(plan_path))
    verify_plan_prompt(paths[0], plan_path)


def verify_requested_effort(path: Path, plan: dict) -> None:
    if not plan.get("hostEffortRequired"):
        return
    contexts = []
    with path.open() as handle:
        for line in handle:
            record = json.loads(line); payload = record.get("payload") or {}
            if record.get("type") == "event_msg" and payload.get("type") == "task_started":
                contexts = []
            elif record.get("type") == "turn_context":
                contexts.append(payload.get("effort", payload.get("reasoning_effort", payload.get("model_reasoning_effort"))))
    if not contexts or any(value != plan["reasoningEffort"] for value in contexts):
        raise DelegateError("Actual host reasoning effort differs from the prepared task")
