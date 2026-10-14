"""Offline fixtures of the desktop schema observed in original 2026-09-06 logs.

The real foundation/pilot records have agent_message input_text envelopes plus
encrypted_content, parent spawn arguments with the same opaque string, nested
exec outputs containing prepare-task results, and assistant phase=final_answer.
All identities, content and ciphertext below are synthetic; original logs are
replayed read-only separately and are never copied into a fixture sessions root.
"""
from __future__ import annotations

import json
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path

import pytest

from tests.test_execution_profiles import project, prepare, run, checks, main_review
from tests.test_workflow_contract import workflow_report
from codex_with_cc_runtime import lifecycle, workflow
from codex_with_cc_runtime.common import DelegateError, REPORT_HEADINGS
from codex_with_cc_runtime.host_evidence import final_response, verify_plan_prompt, verify_active_child
from codex_with_cc_runtime.io_utils import load_json
from codex_with_cc_runtime.native_run import validate_report
from codex_with_cc_runtime.routing import spawn_payload


def write_log(path, records):
    path.write_text("".join(json.dumps(x) + "\n" for x in records))


def desktop_fixture(project, backend="codex-native", *, adaptive=False, monkeypatch=None):
    p, root = project
    if adaptive:
        run("configure-workflow", "-WorkflowId", "new", "-ProjectRoot", str(p),
            "-ArtifactRoot", str(root), "-MaxParallel", "2")
    plan_path = prepare(project, backend)
    plan = load_json(plan_path)
    task_name = "impl_" + plan["planId"][:8]
    agent, thread, turn = "/root/" + task_name, "desktop-child", "desktop-turn"
    opaque = "opaque-test-ciphertext-not-a-real-secret"
    marker = f"WorkflowPlan: {plan_path}"
    start = datetime.fromisoformat(plan["createdAt"])

    def record(kind, payload, second):
        return {"type": kind, "timestamp": (start + timedelta(seconds=second)).isoformat(), "payload": payload}

    args = {"task_name": task_name, "fork_turns": "none", "model": plan["model"],
            "reasoning_effort": plan["reasoningEffort"], "message": opaque}
    parent_path = lifecycle.sessions_root() / "rollout-desktop-parent.jsonl"
    parent_meta = record("session_meta", {"id": "desktop-parent", "cwd": str(p), "source": "cli"}, 0)
    output = spawn_payload(plan_path, plan)
    producer = "prepare-task"
    if adaptive:
        monkeypatch.chdir(p)
        monkeypatch.setenv("CODEX_THREAD_ID", "desktop-parent")
        monkeypatch.delenv("CODEX_CLAUDE_CHILD_THREAD", raising=False)
        write_log(parent_path, [parent_meta])
        emitted = StringIO()
        with redirect_stdout(emitted):
            assert run("admit-task", "-PlanFile", str(plan_path)) == 0
        output = json.loads(emitted.getvalue())
        producer = "admit-task"
    parent = [
        parent_meta,
        record("response_item", {"type": "custom_tool_call", "name": "exec", "call_id": "prepare-call",
            "input": "text(await tools.exec_command({cmd: 'runtime.py " + producer + " ...'}));"}, 0),
        record("response_item", {"type": "custom_tool_call_output", "call_id": "prepare-call", "output": [
            {"type": "input_text", "text": "Script completed\n"},
            {"type": "input_text", "text": json.dumps({"exit_code": 0, "output": json.dumps(output)})}]}, 1),
        record("response_item", {"type": "function_call", "name": "spawn_agent", "namespace": "collaboration",
            "call_id": "spawn-call", "arguments": json.dumps(args)}, 2),
        record("response_item", {"type": "function_call_output", "call_id": "spawn-call",
            "output": json.dumps({"task_name": agent})}, 3),
    ]
    report = workflow_report(role="implementer")
    for heading in REPORT_HEADINGS:
        report = report.replace("\n" + heading + "\n", "\n## " + heading + "\n")
    report = "## " + report
    envelope = f"Message Type: NEW_TASK\nTask name: {agent}\nSender: /root\nPayload:\n"
    child = [
        record("session_meta", {"id": thread, "cwd": str(p), "parent_thread_id": "desktop-parent",
            "source": {"subagent": {"thread_spawn": {"parent_thread_id": "desktop-parent", "agent_path": agent}}}}, 2),
        record("event_msg", {"type": "task_started", "turn_id": turn}, 2),
        record("response_item", {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "Environment instructions; no WorkflowPlan here."}]}, 3),
        record("turn_context", {"turn_id": turn, "model": plan["model"], "effort": plan["reasoningEffort"]}, 3),
        record("response_item", {"type": "agent_message", "author": "/root", "recipient": agent,
            "content": [{"type": "input_text", "text": envelope}, {"type": "encrypted_content", "encrypted_content": opaque}],
            "internal_chat_message_metadata_passthrough": {"turn_id": turn}}, 4),
        record("response_item", {"type": "message", "role": "assistant", "phase": "final_answer",
            "content": [{"type": "output_text", "text": report}],
            "internal_chat_message_metadata_passthrough": {"turn_id": turn}}, 5),
        record("event_msg", {"type": "task_complete", "turn_id": turn, "last_agent_message": "lossy summary"}, 6),
    ]
    child_path = lifecycle.sessions_root() / f"rollout-{thread}.jsonl"
    write_log(parent_path, parent)
    write_log(child_path, child)
    return plan_path, parent_path, child_path, parent, child, agent, report


@pytest.mark.parametrize("backend", ["codex-native", "claude-code"])
@pytest.mark.parametrize("adaptive", [False, True])
def test_desktop_binding_and_native_end_to_end(project, monkeypatch, backend, adaptive):
    plan, pp, cp, parent, child, agent, report = desktop_fixture(project, backend, adaptive=adaptive, monkeypatch=monkeypatch)
    p, root = project
    evidence = verify_plan_prompt(cp, plan)
    assert evidence["source"] == "original-parent-encrypted-dispatch"
    assert "opaque-test" not in json.dumps(evidence)
    assert final_response(cp) == (report, load_json(plan)["model"])
    if backend == "claude-code":
        verify_active_child("desktop-child", str(p), load_json(plan)["model"], plan)
        return
    workflow.record_agent_spawn(root, "new", "impl", agent)
    assert run("record-native-run", "-PlanFile", str(plan), "-AgentId", agent, "-TranscriptPath", str(cp)) == 0
    lifecycle.record_agent_terminal(root, "new", "impl", agent, cp)
    assert main_review(project, monkeypatch, checks(project)) == 0
    assert run("verify-workflow", "-WorkflowId", "new", "-ArtifactRoot", str(root)) == 0
    rid = load_json(workflow.workflow_path(root, "new"))["tasks"]["impl"]["latestRunId"]
    config = load_json(root / f"config_{rid}.json")
    assert Path(config["outputPath"]).read_text() == report
    assert config["planPromptEvidence"] == evidence
    config_path = root / f"config_{rid}.json"
    missing_binding = dict(config)
    missing_binding.pop("planPromptEvidence")
    config_path.write_text(json.dumps(missing_binding))
    with pytest.raises(DelegateError, match="dispatch evidence changed"):
        run("verify-run", "-RunId", rid, "-ArtifactRoot", str(root))
    config_path.write_text(json.dumps(config))
    # Parent activity continues after the child completes; only the linked
    # original records are pinned, never the entire still-active parent file.
    parent.append({"type": "event_msg", "payload": {"type": "token_count"}})
    write_log(pp, parent)
    assert run("verify-run", "-RunId", rid, "-ArtifactRoot", str(root)) == 0
    parent[1]["payload"]["input"] += " changed"
    write_log(pp, parent)
    with pytest.raises(DelegateError, match="dispatch evidence changed"):
        run("verify-run", "-RunId", rid, "-ArtifactRoot", str(root))


@pytest.mark.parametrize("mutation", ["wrong-producer", "missing-admission"])
def test_adaptive_encrypted_dispatch_requires_original_admission(project, monkeypatch, mutation):
    plan, pp, cp, parent, *_ = desktop_fixture(project, adaptive=True, monkeypatch=monkeypatch)
    if mutation == "wrong-producer":
        parent[1]["payload"]["input"] = parent[1]["payload"]["input"].replace("admit-task", "prepare-task")
        write_log(pp, parent)
        error = "preparation evidence"
    else:
        (plan.parent / "admission.json").unlink()
        error = "admission"
    with pytest.raises(DelegateError, match=error):
        verify_plan_prompt(cp, plan)


@pytest.mark.parametrize("mutation", [
    "ciphertext", "recipient", "author", "turn", "missing-parent", "parent-project", "parent-id",
    "missing-preparation", "preparation-path", "preparation-marker", "failed-preparation", "unrelated-tool",
    "missing-result", "wrong-result", "result-call-id", "duplicate-result", "duplicate-spawn",
    "wrong-model", "wrong-effort", "forked-context", "late-preparation", "assistant-only",
    "missing-dispatch", "stale-turn", "multiple-tasks", "malformed-envelope", "ambiguous-handle",
])
def test_encrypted_binding_rejects_mismatched_or_missing_evidence(project, mutation):
    plan, pp, cp, parent, child, agent, _ = desktop_fixture(project)
    delivery = child[4]["payload"]
    args = json.loads(parent[3]["payload"]["arguments"])
    block = json.loads(parent[2]["payload"]["output"][1]["text"])
    preparation = json.loads(block["output"])
    if mutation == "ciphertext": delivery["content"][1]["encrypted_content"] = "different"
    elif mutation in ("recipient", "author"): delivery[mutation] = "/root/unrelated"
    elif mutation == "turn": delivery["internal_chat_message_metadata_passthrough"]["turn_id"] = "old-turn"
    elif mutation == "parent-project": parent[0]["payload"]["cwd"] = "/unrelated"
    elif mutation == "parent-id": parent[0]["payload"]["id"] = "wrong-parent"
    elif mutation == "preparation-path": preparation["planFile"] += ".wrong"
    elif mutation == "preparation-marker": preparation["spawn"]["message"] = "Unrelated instruction"
    elif mutation == "failed-preparation": block["exit_code"] = 1
    elif mutation == "unrelated-tool": parent[1]["payload"]["name"] = "read_file"
    elif mutation == "wrong-result": parent[4]["payload"]["output"] = json.dumps({"task_name": "/root/wrong"})
    elif mutation == "result-call-id": parent[4]["payload"]["call_id"] = "unknown"
    elif mutation == "duplicate-result": parent.append(deepcopy(parent[4]))
    elif mutation == "duplicate-spawn": parent.append(deepcopy(parent[3]))
    elif mutation == "wrong-model": args["model"] = "other-model"
    elif mutation == "wrong-effort": args["reasoning_effort"] = "low"
    elif mutation == "forked-context": args["fork_turns"] = "all"
    elif mutation == "late-preparation": parent[2]["timestamp"] = child[-1]["timestamp"]
    elif mutation == "assistant-only": child[4] = {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": f"WorkflowPlan: {plan}"}]}}
    elif mutation == "stale-turn":
        child.extend([{"type": "event_msg", "payload": {"type": "task_started", "turn_id": "next"}},
                      {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "next"}}])
    elif mutation == "multiple-tasks": child.insert(5, deepcopy(child[4]))
    elif mutation == "malformed-envelope": delivery["content"][0] = None
    elif mutation == "ambiguous-handle":
        wpath = workflow.workflow_path(project[1], "new")
        w = load_json(wpath); key = load_json(plan)["planId"]
        w["preparedTasks"][key[:8] + "f" * 24] = {"taskId": "impl"}
        wpath.write_text(json.dumps(w))
    parent[3]["payload"]["arguments"] = json.dumps(args)
    block["output"] = json.dumps(preparation)
    parent[2]["payload"]["output"][1]["text"] = json.dumps(block)
    if mutation == "missing-preparation": parent.pop(2)
    elif mutation == "missing-result": parent.pop(4)
    elif mutation == "missing-dispatch": child.pop(4)
    write_log(pp, parent); write_log(cp, child)
    if mutation == "missing-parent": pp.unlink()
    with pytest.raises(DelegateError):
        verify_plan_prompt(cp, plan)


def test_plaintext_agent_delivery_and_in_turn_coordination(project):
    plan, pp, cp, _, child, _, _ = desktop_fixture(project)
    delivery = child[4]["payload"]
    delivery["content"] = [{"type": "input_text", "text": delivery["content"][0]["text"] + f"WorkflowPlan: {plan}\nExecute."}]
    note = deepcopy(child[4])
    note["payload"]["content"] = [{"type": "input_text", "text": "Message Type: MESSAGE\nWorkflowPlan: /unrelated"}]
    child.insert(5, note)
    write_log(cp, child); pp.unlink()
    assert verify_plan_prompt(cp, plan)["source"] == "original-agent-instruction"
    child.pop(4)
    write_log(cp, child)
    with pytest.raises(DelegateError): verify_plan_prompt(cp, plan)


@pytest.mark.parametrize("mutation", ["commentary", "conflicting-phase", "stale-final", "wrong-turn", "terminal-summary-only"])
def test_final_response_requires_current_explicit_final(project, mutation):
    _, _, cp, _, child, _, _ = desktop_fixture(project)
    if mutation == "commentary": child[5]["payload"]["phase"] = "commentary"
    elif mutation == "conflicting-phase": child[5]["payload"]["channel"] = "commentary"
    elif mutation == "stale-final": child.append({"type": "event_msg", "payload": {"type": "task_started", "turn_id": "next"}})
    elif mutation == "wrong-turn": child[5]["payload"]["internal_chat_message_metadata_passthrough"]["turn_id"] = "previous"
    elif mutation == "terminal-summary-only": child.pop(5)
    write_log(cp, child)
    with pytest.raises(DelegateError, match="no final response"): final_response(cp)


@pytest.mark.parametrize("mutation", ["missing-heading", "duplicate-heading", "fenced", "unknown-status", "status-mismatch", "wrong-role"])
def test_markdown_report_does_not_relax_semantics(project, mutation):
    *_, report = desktop_fixture(project)
    if mutation == "missing-heading": report = report.replace("## Findings", "## Observations")
    elif mutation == "duplicate-heading": report += "\n## Status\nFAIL\n"
    elif mutation == "fenced": report = "```markdown\n" + report + "\n```"
    elif mutation == "unknown-status": report = report.replace("DONE", "SUCCESS")
    elif mutation == "status-mismatch": report = report.replace("DONE", "FAIL", 1)
    elif mutation == "wrong-role": report = report.replace("implementer", "researcher")
    with pytest.raises(DelegateError): validate_report(report, "implementer")
