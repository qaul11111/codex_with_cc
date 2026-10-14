"""Synthetic fixtures for the separate host/provider IDs observed on 2026-09-16."""
from copy import deepcopy

import pytest

from tests.test_execution_profiles import project
from tests.test_host_log_compat import desktop_fixture, write_log
from codex_with_cc_runtime.common import DelegateError, REPORT_HEADINGS
from codex_with_cc_runtime.host_evidence import final_response
from codex_with_cc_runtime.native_run import validate_report
from codex_with_cc_runtime.reports import report_section


@pytest.mark.parametrize("mutation", [None, "unmatched-call", "wrong-host", "duplicate-call", "late-binding", "new-turn"])
def test_provider_final_turn_requires_prior_current_host_tool_binding(project, mutation):
    _, _, path, _, child, _, report = desktop_fixture(project)
    final = child[5]
    final["payload"]["internal_chat_message_metadata_passthrough"]["turn_id"] = "provider-turn"
    call = {"type": "response_item", "payload": {"type": "custom_tool_call", "call_id": "provider-call",
        "name": "exec", "input": "observed tool request", "internal_chat_message_metadata_passthrough": {"turn_id": "provider-turn"}}}
    output = {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "provider-call",
        "output": "observed tool result", "internal_chat_message_metadata_passthrough": {"turn_id": "desktop-turn"}}}
    child[5:5] = [call, output]
    if mutation == "unmatched-call": output["payload"]["call_id"] = "unrelated"
    elif mutation == "wrong-host": output["payload"]["internal_chat_message_metadata_passthrough"]["turn_id"] = "old-host-turn"
    elif mutation == "duplicate-call": child.insert(6, deepcopy(call))
    elif mutation == "late-binding": child.remove(final); child.insert(5, final)
    elif mutation == "new-turn": child.append({"type": "event_msg", "payload": {"type": "task_started", "turn_id": "next-turn"}})
    write_log(path, child)
    if mutation:
        with pytest.raises(DelegateError, match="no final response"): final_response(path)
    else:
        assert final_response(path)[0] == report


@pytest.mark.parametrize("mutation", [None, "duplicate", "unknown", "contradiction"])
def test_inline_fields_preserve_report_semantics(project, mutation):
    *_, original = desktop_fixture(project)
    report = "\n\n".join(heading + ": " + report_section(original, heading) for heading in REPORT_HEADINGS)
    report = report.replace("Final Result: DONE", "Final Result: DONE. See the verification and original evidence above.")
    if mutation == "duplicate": report += "\nStatus: DONE\n"
    elif mutation == "unknown": report = report.replace("Status: DONE", "Status: SUCCESS")
    elif mutation == "contradiction": report = report.replace("Final Result: DONE.", "Final Result: FAIL.")
    if mutation:
        with pytest.raises(DelegateError): validate_report(report, "implementer")
    else:
        assert validate_report(report, "implementer") is None
