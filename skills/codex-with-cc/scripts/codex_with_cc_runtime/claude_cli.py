from __future__ import annotations

import json
import re
from typing import Any, Iterable

from .reports import text_has_required_report_headings


REPORT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED", "FAIL"]},
        "role": {"type": "string", "enum": ["planner", "implementer", "researcher", "reviewer", "final-verifier"]},
        "summary": {"type": "string"},
        "changedFiles": {"type": "array", "items": {"type": "string"}},
        "verification": {"type": "array", "items": {"type": "string"}},
        "findings": {"type": "array", "items": {"type": "string"}},
        "finalResult": {"type": "string", "enum": ["DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED", "FAIL"]},
        "risksOrFollowUps": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "status",
        "role",
        "summary",
        "changedFiles",
        "verification",
        "findings",
        "finalResult",
        "risksOrFollowUps",
    ],
    "additionalProperties": False,
}


def structured_report_text(value: Any) -> str:
    if not isinstance(value, dict):
        return ""

    def lines(name: str) -> str:
        items = value.get(name)
        if not isinstance(items, list) or not items:
            return "None"
        return "\n".join(f"- {item}" for item in items)

    status = str(value.get("status") or "")
    role = str(value.get("role") or "")
    final_result = str(value.get("finalResult") or "")
    if not status or not role or not final_result:
        return ""
    return f"""Status
{status}

Role
{role}

Summary
{value.get("summary") or "None"}

Changed Files
{lines("changedFiles")}

Verification
{lines("verification")}

Findings
{lines("findings")}

Final Result
{final_result}

Risks Or Follow-ups
{lines("risksOrFollowUps")}
"""


def role_effort(role: str) -> str:
    if role in ("implementer", "final-verifier"):
        return "high"
    return "medium"


def role_disallowed_tools(role: str) -> str:
    tools = ["Agent", "Task"]
    if role in ("planner", "researcher", "reviewer", "final-verifier"):
        tools.extend(["Edit", "Write", "NotebookEdit"])
    return ",".join(tools)



def text_blocks(content: Any) -> list[str]:
    if content is None:
        return []
    items = content if isinstance(content, list) else [content]
    out: list[str] = []
    for item in items:
        if isinstance(item, dict) and item.get("type") == "text" and str(item.get("text", "")).strip():
            out.append(str(item["text"]))
    return out



def update_stream_capture(record: dict[str, Any], state: dict[str, Any]) -> list[str]:
    state.setdefault("assistantTexts", [])
    state.setdefault("traceLines", [])
    state.setdefault("finalText", "")
    state.setdefault("sawAssistantText", False)
    state.setdefault("sawResultSuccess", False)
    state.setdefault("capturedFinalResultHeading", False)
    state.setdefault("totalCostUsd", None)
    state.setdefault("usage", {})
    state.setdefault("modelUsage", {})
    state.setdefault("models", [])

    trace_lines: list[str] = []
    record_type = str(record.get("type", ""))
    if record_type == "system":
        parts = ["[system]"]
        if record.get("subtype"):
            parts.append(str(record["subtype"]))
        if record.get("status"):
            parts.append(str(record["status"]))
        trace_lines.append(" ".join(parts))
    elif record_type == "assistant":
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        message_id = message.get("id")
        trace_lines.append(f"[assistant] message={message_id}" if message_id else "[assistant]")
        if isinstance(message.get("usage"), dict):
            state["usage"] = message["usage"]
        if message.get("model") and message["model"] not in state["models"]:
            state["models"].append(message["model"])
        texts = text_blocks(message.get("content"))
        if texts:
            text = "\n".join(texts).strip()
            if text:
                state["sawAssistantText"] = True
                if text_has_required_report_headings(text):
                    state["capturedFinalResultHeading"] = True
                state["assistantTexts"].append(text)
                state["finalText"] = text
    elif record_type == "result":
        subtype = str(record.get("subtype", ""))
        line = "[result]"
        if subtype:
            line += f" {subtype}"
        reported_cost = record.get("total_cost_usd", record.get("cost_usd"))
        if reported_cost is not None:
            state["totalCostUsd"] = reported_cost
            line += f" cost={reported_cost}"
        if isinstance(record.get("usage"), dict):
            state["usage"] = record["usage"]
        if isinstance(record.get("modelUsage"), dict):
            state["modelUsage"] = record["modelUsage"]
        structured_text = structured_report_text(record.get("structured_output"))
        if structured_text:
            state["sawAssistantText"] = True
            state["capturedFinalResultHeading"] = True
            state["assistantTexts"].append(structured_text)
            state["finalText"] = structured_text
        if subtype == "success":
            state["sawResultSuccess"] = True
        trace_lines.append(line)
    elif record_type == "stream_event":
        event = record.get("event") if isinstance(record.get("event"), dict) else {}
        event_type = str(event.get("type", ""))
        trace_lines.append(f"[stream] {event_type}" if event_type else "[stream]")
    elif record_type:
        trace_lines.append(f"[{record_type}]")
    else:
        trace_lines.append("[unknown-record]")
    state["traceLines"].extend(trace_lines)
    return trace_lines



def new_claude_cli_args(
    model: str,
    session_name: str,
    role: str,
    session_id: str,
    resume: bool,
    max_budget_usd: str | None,
    bypass_permissions: bool,
    effort: str | None = None,
) -> list[str]:
    args = [
        "--verbose",
        "--print",
        "--output-format",
        "stream-json",
        "--input-format",
        "text",
        "--model",
        model,
        "--name",
        session_name,
        "--effort",
        effort or role_effort(role),
        "--disallowed-tools",
        role_disallowed_tools(role),
        "--json-schema",
        json.dumps(REPORT_JSON_SCHEMA, separators=(",", ":")),
        "--permission-mode",
        "bypassPermissions" if bypass_permissions else "acceptEdits",
    ]
    args.extend(["--resume" if resume else "--session-id", session_id])
    if max_budget_usd not in (None, ""):
        args.extend(["--max-budget-usd", str(max_budget_usd)])
    if bypass_permissions:
        args.append("--dangerously-skip-permissions")
    return args



def non_json_raw_lines(raw_lines: Iterable[str]) -> list[str]:
    out: list[str] = []
    for line in raw_lines:
        if not str(line).strip():
            continue
        try:
            json.loads(str(line))
        except json.JSONDecodeError:
            out.append(str(line).strip())
    return out



def retry_decision(
    raw_lines: Iterable[str],
    resume_attempt: bool,
    exit_code: int,
    saw_assistant_text: bool,
    saw_result_success: bool,
    captured_final_result_heading: bool,
) -> dict[str, Any]:
    raw_line_list = [str(line).strip() for line in raw_lines if str(line).strip()]
    joined = "\n".join(non_json_raw_lines(raw_line_list))
    joined_all = "\n".join(raw_line_list)
    saw_stale = re.search(r"No conversation found.*session ID", joined) is not None
    saw_stream_json = re.search(r"stream-json.*requires.*--verbose", joined) is not None
    saw_socket_closed = re.search(r"socket connection was closed unexpectedly", joined_all, re.IGNORECASE) is not None
    has_structured_success = saw_result_success and captured_final_result_heading
    decision = {
        "shouldRetry": False,
        "retryReason": "",
        "retryWithFreshSession": False,
        "retryWithResumeSession": False,
        "sawStaleSessionText": saw_stale,
        "sawStreamJsonVerboseError": saw_stream_json,
        "sawSocketClosedText": saw_socket_closed,
        "hasStructuredSuccess": has_structured_success,
        "exitCode": exit_code,
        "sawAssistantText": saw_assistant_text,
        "sawResultSuccess": saw_result_success,
        "capturedFinalResultHeading": captured_final_result_heading,
        "retryWithReportRepair": False,
    }
    if resume_attempt and saw_stale and not has_structured_success:
        decision.update({"shouldRetry": True, "retryReason": "stale_claude_session", "retryWithFreshSession": True})
    elif saw_stream_json and not has_structured_success:
        decision.update({"shouldRetry": True, "retryReason": "stream_json_startup", "retryWithFreshSession": False})
    elif saw_socket_closed and saw_assistant_text and not has_structured_success:
        decision.update({"shouldRetry": True, "retryReason": "socket_transport_after_progress", "retryWithResumeSession": True})
    elif exit_code == 0 and saw_result_success and saw_assistant_text and not has_structured_success:
        decision.update(
            {
                "shouldRetry": True,
                "retryReason": "unstructured_success_report",
                "retryWithFreshSession": False,
                "retryWithReportRepair": True,
            }
        )
    return decision



def failure_summary(raw_lines: Iterable[str], retry_reason: str | None, attempt_count: int, max_retry_count: int, exit_code: int) -> str:
    seen: list[str] = []
    for line in non_json_raw_lines(raw_lines):
        if line not in seen:
            seen.append(line)
        if len(seen) >= 2:
            break
    snippet = " | ".join(seen) if seen else "No non-JSON stderr summary was captured."
    reason = retry_reason or "unknown_retry_condition"
    max_attempts = max_retry_count + 1
    return (
        f"NEED_HUMAN_INTERVENTION after exhausting retry budget. retryReason={reason}. "
        f"attempt {attempt_count}/{max_attempts}. exitCode={exit_code}. {snippet}"
    )
