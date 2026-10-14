"""Offline fixtures only: no model calls and no fabricated production evidence.

Historical verification supplements let a superseded (not current/latest) DONE
delegate report gain independently re-derivable evidence for declared tests it
abbreviated, by binding each missing command to the exact Bash
tool_use/tool_result pair in the run's original raw stream. Every artifact in
this module is synthetic and lives under tmp_path; nothing touches the real
workflow artifacts being repaired.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "codex-with-cc" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from codex_with_cc_runtime import artifacts
from codex_with_cc_runtime import cli
from codex_with_cc_runtime import verification_supplements as supplements
from codex_with_cc_runtime import workflow as wf
from codex_with_cc_runtime.common import (
    ARTIFACT_SCHEMA_VERSION,
    CHILD_MARKER_NAME,
    INVOCATION_CONTRACT,
    DelegateError,
)
from codex_with_cc_runtime.io_utils import load_json

SESSION = "11111111-2222-4333-8444-555555555555"
OLD_RUN = "20260904_200000_000_aaaa0001"
NEW_RUN = "20260904_210000_000_bbbb0002"
TASK = "final"
WF = "wf-supplements"
DECLARED_A = "probe alpha --strict"
DECLARED_B = "probe beta --strict"

BASE_ATTEMPT = {
    "attempt": 1,
    "sessionId": SESSION,
    "resume": False,
    "retryReason": None,
    "exitCode": 0,
    "sawAssistantText": True,
    "sawResultSuccess": True,
    "capturedFinalResult": True,
}


def report_text(verification: str, status: str = "DONE", role: str = "final-verifier") -> str:
    return (
        f"Status\n{status}\n\n"
        f"Role\n{role}\n\n"
        "Summary\nOffline fixture report.\n\n"
        "Changed Files\nNone\n\n"
        f"Verification\n{verification}\n\n"
        "Findings\n- offline fixture\n\n"
        f"Final Result\n{status}\n\n"
        "Risks Or Follow-ups\n- offline fixture only\n"
    )


def bash_use(uid: str, command: str, session: str = SESSION) -> dict:
    return {
        "type": "assistant",
        "session_id": session,
        "uuid": f"use-{uid}",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": uid, "name": "Bash", "input": {"command": command}}
            ],
        },
    }


def bash_result(uid: str, session: str = SESSION, *, is_error=False, tool_use_result=None, drop_result=False) -> dict:
    if tool_use_result is None and not drop_result:
        tool_use_result = {
            "stdout": "ok",
            "stderr": "",
            "interrupted": False,
            "isImage": False,
            "noOutputExpected": False,
        }
    record = {
        "type": "user",
        "session_id": session,
        "uuid": f"res-{uid}",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": uid, "content": "ok", "is_error": is_error}
            ],
        },
    }
    if not drop_result:
        record["tool_use_result"] = tool_use_result
    return record


def default_stream(session: str = SESSION) -> list:
    return [
        {"type": "system", "subtype": "init", "session_id": session},
        {"type": "system", "subtype": "thinking_tokens", "session_id": session},
        bash_use("toolu_alpha", DECLARED_A, session=session),
        bash_result("toolu_alpha", session=session),
        bash_use("toolu_beta", DECLARED_B, session=session),
        bash_result("toolu_beta", session=session),
        {"type": "result", "subtype": "success", "session_id": session},
    ]


def save(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_run(
    root: Path,
    run_id: str,
    *,
    tests: list[str],
    verification: str,
    report_status: str = "DONE",
    stream_records: list | None = None,
    session: str = SESSION,
    config_over: dict | None = None,
    status_over: dict | None = None,
) -> None:
    report = root / f"claude_{run_id}.md"
    report.write_text(report_text(verification, status=report_status), encoding="utf-8")
    stream = root / f"stream_{run_id}.jsonl"
    records = default_stream(session) if stream_records is None else stream_records
    lines = [record if isinstance(record, str) else json.dumps(record) for record in records]
    stream.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    common = {
        "artifactSchema": ARTIFACT_SCHEMA_VERSION,
        "invocationContract": INVOCATION_CONTRACT,
        "childThreadMarkerName": CHILD_MARKER_NAME,
        "childThreadMarkerValidated": True,
        "workflowId": WF,
        "taskId": TASK,
        "runId": run_id,
        "role": "final-verifier",
        "outputPath": str(report),
        "exitCode": 0,
        "attemptCount": 1,
        "retryCount": 0,
        "runnerType": "claude_code",
        "tests": list(tests),
        "rawStreamPath": str(stream),
    }
    config = {
        **common,
        "repoRoot": str(root),
        "sessionMode": "ParallelPool",
        "sessionKey": "sess-key",
        "initialSessionId": session,
        "initialResume": False,
        "sessionId": session,
        "resume": False,
        "dryRun": False,
        "trustedLocalFallback": False,
        "sessionStatePath": str(root / f"session_{run_id}.json"),
        "statusPath": str(root / f"status_{run_id}.json"),
    }
    if config_over:
        config.update(config_over)
    status = {
        **common,
        "status": "completed",
        "pid": 424242,
        "attempts": [dict(BASE_ATTEMPT, sessionId=session)],
    }
    if status_over:
        status.update(status_over)
    config_path = root / f"config_{run_id}.json"
    status_path = root / f"status_{run_id}.json"
    save(config_path, config)
    save(status_path, status)
    save(root / f"session_{run_id}.json", {"parallelPool": []})
    wf.update_workflow_record(
        root,
        WF,
        TASK,
        "final-verifier",
        [],
        list(tests),
        [],
        run_id,
        config_path,
        status_path,
        report,
        root / f"prompt_{run_id}.md",
        stream,
        root / f"trace_{run_id}.log",
        "completed",
    )


def build_env(tmp_path: Path, *, old: dict | None = None, new: dict | None = None) -> Path:
    root = tmp_path / "artifacts"
    root.mkdir()
    tests = [DECLARED_A, DECLARED_B]
    old_opts = dict(old or {})
    new_opts = dict(new or {})
    old_opts.setdefault("verification", f"- {DECLARED_A} — exit 0\n- abbreviated legacy checks")
    new_opts.setdefault("verification", f"- {DECLARED_A} — exit 0\n- {DECLARED_B} — exit 0")
    write_run(root, OLD_RUN, tests=tests, **old_opts)
    write_run(root, NEW_RUN, tests=tests, **new_opts)
    return root


def verify_workflow(root: Path) -> int:
    return artifacts.run_verify_workflow(argparse.Namespace(workflow_id=WF, artifact_root=str(root)))


def snapshot_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.name: path.read_bytes()
        for path in sorted(root.iterdir())
        if path.is_file() and not path.name.startswith(".")
    }


def supplement_file(root: Path) -> Path:
    return root / f"verification-supplement_{OLD_RUN}.json"


def test_baseline_omission_fails_gate_with_run_and_task_id(tmp_path):
    root = build_env(tmp_path)
    with pytest.raises(DelegateError) as excinfo:
        verify_workflow(root)
    message = str(excinfo.value)
    assert OLD_RUN in message
    assert TASK in message
    assert DECLARED_B in message
    assert not supplement_file(root).exists()


def test_record_supplement_then_gate_passes(tmp_path):
    root = build_env(tmp_path)
    path = supplements.record_verification_supplement(OLD_RUN, str(root))
    assert path == supplement_file(root)
    sidecar = load_json(path)
    assert sidecar["schema"] == "codex-with-cc-verification-supplement"
    assert sidecar["schemaVersion"] == 1
    assert sidecar["runId"] == OLD_RUN
    assert sidecar["taskId"] == TASK
    assert sidecar["workflowId"] == WF
    assert sidecar["sessionId"] == SESSION
    commands = sidecar["commands"]
    assert [item["command"] for item in commands] == [DECLARED_B]
    entry = commands[0]
    assert entry["toolUseId"] == "toolu_beta"
    # Bare Claude tool result: tool-reported success only, no invented numeric exit 0.
    assert entry["evidence"] == "tool-reported-success"
    assert entry["exitCode"] is None
    assert entry["use"]["line"] < entry["result"]["line"]
    hashes = sidecar["sha256"]
    assert hashes["config"] == sha256(root / f"config_{OLD_RUN}.json")
    assert hashes["status"] == sha256(root / f"status_{OLD_RUN}.json")
    assert hashes["report"] == sha256(root / f"claude_{OLD_RUN}.md")
    assert hashes["stream"] == sha256(root / f"stream_{OLD_RUN}.jsonl")
    assert verify_workflow(root) == 0


def test_exit_code_zero_result_recorded_as_exit_code_evidence(tmp_path):
    records = [
        bash_use("toolu_beta", DECLARED_B),
        bash_result(
            "toolu_beta",
            tool_use_result={
                "stdout": "ok",
                "stderr": "",
                "interrupted": False,
                "isImage": False,
                "noOutputExpected": False,
                "exitCode": 0,
            },
        ),
    ]
    root = build_env(tmp_path, old={"stream_records": records})
    sidecar = load_json(supplements.record_verification_supplement(OLD_RUN, str(root)))
    entry = sidecar["commands"][0]
    assert entry["evidence"] == "exit-code-0"
    assert entry["exitCode"] == 0
    assert verify_workflow(root) == 0


def test_record_is_idempotent_without_rewriting(tmp_path):
    root = build_env(tmp_path)
    path = supplements.record_verification_supplement(OLD_RUN, str(root))
    before = path.read_bytes()
    again = supplements.record_verification_supplement(OLD_RUN, str(root))
    assert again == path
    assert path.read_bytes() == before


def test_existing_conflicting_sidecar_fails_safely_without_rewriting(tmp_path):
    root = build_env(tmp_path)
    path = supplements.record_verification_supplement(OLD_RUN, str(root))
    forged_data = load_json(path)
    forged_data["commands"][0]["command"] = "forged command"
    path.write_text(json.dumps(forged_data, indent=2), encoding="utf-8")
    forged = path.read_bytes()
    with pytest.raises(DelegateError):
        supplements.record_verification_supplement(OLD_RUN, str(root))
    assert path.read_bytes() == forged


def test_record_does_not_mutate_original_artifacts(tmp_path):
    root = build_env(tmp_path)
    before = snapshot_bytes(root)
    supplements.record_verification_supplement(OLD_RUN, str(root))
    after = snapshot_bytes(root)
    assert set(after) - set(before) == {supplement_file(root).name}
    for name, blob in before.items():
        assert after[name] == blob


def test_current_latest_run_cannot_use_supplement(tmp_path):
    root = build_env(tmp_path)
    with pytest.raises(DelegateError, match="current"):
        supplements.record_verification_supplement(NEW_RUN, str(root))


def test_superseded_report_with_complete_evidence_needs_no_supplement(tmp_path):
    root = build_env(tmp_path, old={"verification": f"- {DECLARED_A} — exit 0\n- {DECLARED_B} — exit 0"})
    with pytest.raises(DelegateError, match="no missing declared"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


def test_non_done_superseded_report_rejected(tmp_path):
    root = build_env(tmp_path, old={"report_status": "DONE_WITH_CONCERNS"})
    with pytest.raises(DelegateError, match="DONE"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


def test_run_id_binding_mismatch_rejected(tmp_path):
    root = build_env(tmp_path, old={"config_over": {"runId": "someone-else"}})
    with pytest.raises(DelegateError, match="runId"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


@pytest.mark.parametrize(
    "config_over,status_over,match",
    [
        ({"dryRun": True}, None, "dry-run"),
        (None, {"attempts": [dict(BASE_ATTEMPT, dryRun=True)]}, "dry-run"),
        ({"trustedLocalFallback": True}, None, "fallback"),
        ({"artifactRootFallbackReason": "primary root missing"}, None, "fallback"),
        (None, {"statusRecoveredFromReport": True}, "recovered"),
        ({"runnerType": "openai_compatible"}, None, "claude_code"),
    ],
)
def test_ineligible_runs_rejected(tmp_path, config_over, status_over, match):
    root = build_env(tmp_path, old={"config_over": config_over, "status_over": status_over})
    with pytest.raises(DelegateError, match=match):
        supplements.record_verification_supplement(OLD_RUN, str(root))


def test_multi_attempt_run_rejected(tmp_path):
    attempts = [
        dict(BASE_ATTEMPT, exitCode=1, sawResultSuccess=False, capturedFinalResult=False),
        dict(
            BASE_ATTEMPT,
            attempt=2,
            sessionId=f"{SESSION}-retry",
            resume=True,
            retryReason="transient failure",
        ),
    ]
    root = build_env(
        tmp_path,
        old={
            "config_over": {
                "attemptCount": 2,
                "retryCount": 1,
                "sessionId": f"{SESSION}-retry",
                "resume": True,
            },
            "status_over": {"attempts": attempts, "attemptCount": 2, "retryCount": 1},
        },
    )
    with pytest.raises(DelegateError, match="single-attempt"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


@pytest.mark.parametrize(
    "command",
    [
        "probe beta --strict --verbose",
        "probe beta",
        " probe beta --strict ",
    ],
)
def test_inexact_command_is_not_evidence(tmp_path, command):
    records = [bash_use("toolu_beta", command), bash_result("toolu_beta")]
    root = build_env(tmp_path, old={"stream_records": records})
    with pytest.raises(DelegateError, match="no stream evidence"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


def test_is_error_result_rejected(tmp_path):
    records = [bash_use("toolu_beta", DECLARED_B), bash_result("toolu_beta", is_error=True)]
    root = build_env(tmp_path, old={"stream_records": records})
    with pytest.raises(DelegateError, match="is_error"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


def test_interrupted_result_rejected(tmp_path):
    records = [
        bash_use("toolu_beta", DECLARED_B),
        bash_result("toolu_beta", tool_use_result={"stdout": "", "stderr": "", "interrupted": True}),
    ]
    root = build_env(tmp_path, old={"stream_records": records})
    with pytest.raises(DelegateError, match="interrupted"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


@pytest.mark.parametrize("exit_code", [1, 2, -1])
def test_nonzero_exit_code_result_rejected(tmp_path, exit_code):
    records = [
        bash_use("toolu_beta", DECLARED_B),
        bash_result(
            "toolu_beta",
            tool_use_result={
                "stdout": "ok",
                "stderr": "",
                "interrupted": False,
                "exitCode": exit_code,
            },
        ),
    ]
    root = build_env(tmp_path, old={"stream_records": records})
    with pytest.raises(DelegateError, match="exitCode"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


def test_background_or_pending_result_shape_rejected(tmp_path):
    records = [
        bash_use("toolu_beta", DECLARED_B),
        bash_result(
            "toolu_beta",
            tool_use_result={"stdout": "launched", "interrupted": False, "backgroundTaskId": "task-9"},
        ),
    ]
    root = build_env(tmp_path, old={"stream_records": records})
    with pytest.raises(DelegateError, match="unsupported"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


def test_unstructured_tool_use_result_rejected(tmp_path):
    records = [bash_use("toolu_beta", DECLARED_B), bash_result("toolu_beta", drop_result=True)]
    root = build_env(tmp_path, old={"stream_records": records})
    with pytest.raises(DelegateError, match="structured"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


def test_stream_from_wrong_session_rejected(tmp_path):
    root = build_env(tmp_path, old={"stream_records": default_stream(session="other-session")})
    with pytest.raises(DelegateError, match="session"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


def test_missing_tool_result_rejected(tmp_path):
    root = build_env(tmp_path, old={"stream_records": [bash_use("toolu_beta", DECLARED_B)]})
    with pytest.raises(DelegateError, match="missing tool_result"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


def test_duplicate_tool_result_rejected(tmp_path):
    records = [
        bash_use("toolu_beta", DECLARED_B),
        bash_result("toolu_beta"),
        bash_result("toolu_beta"),
    ]
    root = build_env(tmp_path, old={"stream_records": records})
    with pytest.raises(DelegateError, match="duplicate tool_result"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


def test_reordered_result_before_use_rejected(tmp_path):
    records = [bash_result("toolu_beta"), bash_use("toolu_beta", DECLARED_B)]
    root = build_env(tmp_path, old={"stream_records": records})
    with pytest.raises(DelegateError, match="reordered"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


def test_duplicate_command_invocations_are_ambiguous(tmp_path):
    records = [
        bash_use("toolu_one", DECLARED_B),
        bash_result("toolu_one"),
        bash_use("toolu_two", DECLARED_B),
        bash_result("toolu_two"),
    ]
    root = build_env(tmp_path, old={"stream_records": records})
    with pytest.raises(DelegateError, match="ambiguous"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


def test_duplicate_tool_use_id_rejected(tmp_path):
    records = [
        bash_use("toolu_beta", DECLARED_A),
        bash_result("toolu_beta"),
        bash_use("toolu_beta", DECLARED_B),
        bash_result("toolu_beta"),
    ]
    root = build_env(tmp_path, old={"stream_records": records})
    with pytest.raises(DelegateError, match="duplicate tool_use"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


def test_text_or_read_records_are_not_evidence(tmp_path):
    records = [
        {
            "type": "assistant",
            "session_id": SESSION,
            "uuid": "t1",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": f"I ran {DECLARED_B} and it passed"}],
            },
        },
        {
            "type": "assistant",
            "session_id": SESSION,
            "uuid": "t2",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "toolu_read", "name": "Read", "input": {"file_path": DECLARED_B}}
                ],
            },
        },
        bash_result("toolu_read"),
    ]
    root = build_env(tmp_path, old={"stream_records": records})
    with pytest.raises(DelegateError, match="no stream evidence"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


def test_malformed_json_record_after_content_rejected(tmp_path):
    records = [
        json.dumps(bash_use("toolu_beta", DECLARED_B)),
        "this is not a json record",
        json.dumps(bash_result("toolu_beta")),
    ]
    root = build_env(tmp_path, old={"stream_records": records})
    with pytest.raises(DelegateError, match="Malformed stream record"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


def test_garbage_leading_line_rejected(tmp_path):
    records = ["garbage that is not a known warning"] + default_stream()
    root = build_env(tmp_path, old={"stream_records": records})
    with pytest.raises(DelegateError, match="Malformed stream record"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


def test_known_leading_cli_warning_line_allowed(tmp_path):
    records = default_stream()
    records.insert(2, '[claude-code:unrecognized_model] {"model":"fixture"}')
    root = build_env(tmp_path, old={"stream_records": records})
    sidecar = load_json(supplements.record_verification_supplement(OLD_RUN, str(root)))
    assert [item["command"] for item in sidecar["commands"]] == [DECLARED_B]
    assert verify_workflow(root) == 0


def test_symlink_stream_rejected(tmp_path):
    root = build_env(tmp_path)
    stream = root / f"stream_{OLD_RUN}.jsonl"
    target = root / "stream-copy.jsonl"
    target.write_bytes(stream.read_bytes())
    stream.unlink()
    stream.symlink_to(target.name)
    with pytest.raises(DelegateError, match="symlink"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


def test_stream_outside_artifact_root_rejected(tmp_path):
    outside = tmp_path / "outside-stream.jsonl"
    outside.write_text(
        "".join(json.dumps(record) + "\n" for record in default_stream()), encoding="utf-8"
    )
    root = build_env(
        tmp_path,
        old={
            "config_over": {"rawStreamPath": str(outside)},
            "status_over": {"rawStreamPath": str(outside)},
        },
    )
    with pytest.raises(DelegateError, match="escapes"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


@pytest.mark.parametrize("bad_run_id", ["../escape", "a/b", "..", ""])
def test_unsafe_run_id_rejected(tmp_path, bad_run_id):
    root = build_env(tmp_path)
    with pytest.raises(DelegateError):
        supplements.record_verification_supplement(bad_run_id, str(root))


def test_record_requires_valid_existing_artifacts(tmp_path):
    root = build_env(tmp_path)
    config_path = root / f"config_{OLD_RUN}.json"
    config = load_json(config_path)
    del config["artifactSchema"]
    save(config_path, config)
    with pytest.raises(DelegateError):
        supplements.record_verification_supplement(OLD_RUN, str(root))
    assert not supplement_file(root).exists()


@pytest.mark.parametrize("target", ["config", "status", "report", "stream"])
def test_tampered_original_invalidates_supplement(tmp_path, target):
    root = build_env(tmp_path)
    supplements.record_verification_supplement(OLD_RUN, str(root))
    assert verify_workflow(root) == 0
    names = {
        "config": f"config_{OLD_RUN}.json",
        "status": f"status_{OLD_RUN}.json",
        "report": f"claude_{OLD_RUN}.md",
        "stream": f"stream_{OLD_RUN}.jsonl",
    }
    victim = root / names[target]
    victim.write_bytes(victim.read_bytes() + b" \n")
    with pytest.raises(DelegateError):
        verify_workflow(root)


@pytest.mark.parametrize("mutation", ["command", "sha", "extra-key", "drop-recordedAt"])
def test_tampered_sidecar_fails_gate_with_run_id(tmp_path, mutation):
    root = build_env(tmp_path)
    path = supplements.record_verification_supplement(OLD_RUN, str(root))
    data = load_json(path)
    if mutation == "command":
        data["commands"][0]["command"] = "forged command"
    elif mutation == "sha":
        data["sha256"]["stream"] = "0" * 64
    elif mutation == "extra-key":
        data["trusted"] = True
    elif mutation == "drop-recordedAt":
        del data["recordedAt"]
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    with pytest.raises(DelegateError) as excinfo:
        verify_workflow(root)
    assert OLD_RUN in str(excinfo.value)


def test_malformed_sidecar_json_fails_gate_not_silently_ignored(tmp_path):
    root = build_env(tmp_path)
    path = supplements.record_verification_supplement(OLD_RUN, str(root))
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(DelegateError) as excinfo:
        verify_workflow(root)
    assert OLD_RUN in str(excinfo.value)


def test_cli_record_verification_supplement(tmp_path):
    root = build_env(tmp_path)
    exit_code = cli.main(["record-verification-supplement", "-RunId", OLD_RUN, "-ArtifactRoot", str(root)])
    assert exit_code == 0
    assert supplement_file(root).exists()
    assert verify_workflow(root) == 0
    second = cli.main(["record-verification-supplement", "-RunId", OLD_RUN, "-ArtifactRoot", str(root)])
    assert second == 0


def _alias_fixture(tmp_path):
    """Canonical base with actual/ tree and alias -> actual symlink."""
    base = Path(tmp_path).resolve()
    actual = base / "actual"
    actual.mkdir()
    root = build_env(actual)
    alias = base / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    return base, actual, root, alias


def test_artifact_root_ancestor_symlink_rejected_on_record(tmp_path):
    base, actual, root, alias = _alias_fixture(tmp_path)
    with pytest.raises(DelegateError, match="symlink"):
        supplements.record_verification_supplement(OLD_RUN, str(alias / "artifacts"))
    assert not supplement_file(root).exists()


def test_loading_valid_sidecar_through_alias_rejected(tmp_path):
    base, actual, root, alias = _alias_fixture(tmp_path)
    supplements.record_verification_supplement(OLD_RUN, str(root))
    assert supplement_file(root).exists()
    with pytest.raises(DelegateError, match="symlink"):
        supplements.load_and_verify_supplement(alias / "artifacts", OLD_RUN)
    # The canonical root still verifies the same sidecar.
    covered = supplements.load_and_verify_supplement(root, OLD_RUN)
    assert covered == [DECLARED_B]


def test_direct_root_alias_rejected(tmp_path):
    base, actual, root, alias = _alias_fixture(tmp_path)
    direct = base / "direct-alias"
    direct.symlink_to(root, target_is_directory=True)
    with pytest.raises(DelegateError, match="symlink"):
        supplements.record_verification_supplement(OLD_RUN, str(direct))
    assert not supplement_file(root).exists()


def test_cli_rejects_alias_artifact_root(tmp_path):
    base, actual, root, alias = _alias_fixture(tmp_path)
    exit_code = cli.main(["record-verification-supplement", "-RunId", OLD_RUN, "-ArtifactRoot", str(alias / "artifacts")])
    assert exit_code == 1
    assert not supplement_file(root).exists()


def test_canonical_root_record_and_idempotence_with_alias_present(tmp_path):
    base, actual, root, alias = _alias_fixture(tmp_path)
    path = supplements.record_verification_supplement(OLD_RUN, str(root))
    before = path.read_bytes()
    again = supplements.record_verification_supplement(OLD_RUN, str(root))
    assert again == path
    assert path.read_bytes() == before
    assert verify_workflow(root) == 0


def test_missing_artifact_root_fails_closed(tmp_path):
    base = Path(tmp_path).resolve()
    actual = base / "actual"
    actual.mkdir()
    build_env(actual)
    with pytest.raises(DelegateError):
        supplements.record_verification_supplement(OLD_RUN, str(base / "missing" / "artifacts"))


def test_relative_canonical_root_allowed_but_alias_rejected(tmp_path, monkeypatch):
    base, actual, root, alias = _alias_fixture(tmp_path)
    monkeypatch.chdir(base)
    path = supplements.record_verification_supplement(OLD_RUN, "actual/artifacts")
    assert path == supplement_file(root)
    with pytest.raises(DelegateError, match="symlink"):
        supplements.record_verification_supplement(OLD_RUN, "alias/artifacts")


def test_in_root_sidecar_symlink_rejected(tmp_path):
    root = build_env(tmp_path)
    path = supplements.record_verification_supplement(OLD_RUN, str(root))
    stored = root / "stored-sidecar.json"
    path.rename(stored)
    path.symlink_to(stored)
    with pytest.raises(DelegateError, match="symlink"):
        verify_workflow(root)
    with pytest.raises(DelegateError, match="symlink"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


def test_sidecar_is_not_created_through_dangling_symlink(tmp_path):
    root = build_env(tmp_path)
    path = supplement_file(root)
    path.symlink_to(root / "nonexistent-target.json")
    with pytest.raises(DelegateError, match="symlink"):
        supplements.record_verification_supplement(OLD_RUN, str(root))
    assert path.is_symlink()
    assert not (root / "nonexistent-target.json").exists()


def test_forged_sidecar_for_current_run_fails_gate(tmp_path):
    root = build_env(tmp_path)
    supplements.record_verification_supplement(OLD_RUN, str(root))
    (root / f"verification-supplement_{NEW_RUN}.json").write_text('{"forged": true}', encoding="utf-8")
    with pytest.raises(DelegateError) as excinfo:
        verify_workflow(root)
    assert NEW_RUN in str(excinfo.value)


def test_forged_sidecar_for_non_done_run_fails_gate(tmp_path):
    root = build_env(tmp_path, old={"report_status": "DONE_WITH_CONCERNS"})
    supplement_file(root).write_text('{"forged": true}', encoding="utf-8")
    with pytest.raises(DelegateError) as excinfo:
        verify_workflow(root)
    assert OLD_RUN in str(excinfo.value)


def test_multi_tool_result_record_attribution_rejected(tmp_path):
    ambiguous = {
        "type": "user",
        "session_id": SESSION,
        "uuid": "multi-1",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_beta", "content": "ok", "is_error": False},
                {"type": "tool_result", "tool_use_id": "toolu_other", "content": "ok", "is_error": False},
            ],
        },
        "tool_use_result": {"stdout": "ok", "stderr": "", "interrupted": False},
    }
    records = [bash_use("toolu_beta", DECLARED_B), ambiguous]
    root = build_env(tmp_path, old={"stream_records": records})
    with pytest.raises(DelegateError, match="ambiguous"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


def test_unrelated_multi_tool_result_record_is_ignored(tmp_path):
    unrelated = {
        "type": "user",
        "session_id": SESSION,
        "uuid": "multi-2",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_x", "content": "a", "is_error": False},
                {"type": "tool_result", "tool_use_id": "toolu_y", "content": "b", "is_error": False},
            ],
        },
    }
    records = [bash_use("toolu_beta", DECLARED_B), bash_result("toolu_beta"), unrelated]
    root = build_env(tmp_path, old={"stream_records": records})
    sidecar = load_json(supplements.record_verification_supplement(OLD_RUN, str(root)))
    assert [item["command"] for item in sidecar["commands"]] == [DECLARED_B]


@pytest.mark.parametrize(
    "target",
    ["config", "status", "report"],
)
def test_symlinked_original_artifact_rejected(tmp_path, target):
    root = build_env(tmp_path)
    names = {
        "config": f"config_{OLD_RUN}.json",
        "status": f"status_{OLD_RUN}.json",
        "report": f"claude_{OLD_RUN}.md",
    }
    victim = root / names[target]
    stored = root / f"stored-{names[target]}"
    victim.rename(stored)
    victim.symlink_to(stored)
    with pytest.raises(DelegateError, match="symlink"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


def test_stream_must_be_exact_expected_run_stream(tmp_path):
    root = build_env(tmp_path)
    stray = root / "renamed-stream.jsonl"
    stray.write_bytes((root / f"stream_{OLD_RUN}.jsonl").read_bytes())
    for name in (f"config_{OLD_RUN}.json", f"status_{OLD_RUN}.json"):
        path = root / name
        data = load_json(path)
        data["rawStreamPath"] = str(stray)
        save(path, data)
    with pytest.raises(DelegateError, match="stream"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


def test_workflow_stream_binding_mismatch_rejected(tmp_path):
    root = build_env(tmp_path)
    workflow_path = root / f"workflow_{WF}.json"
    workflow = load_json(workflow_path)
    workflow["runs"][OLD_RUN]["rawStreamPath"] = str(root / "somewhere-else.jsonl")
    save(workflow_path, workflow)
    with pytest.raises(DelegateError, match="stream"):
        supplements.record_verification_supplement(OLD_RUN, str(root))


def test_non_string_session_metadata_rejected(tmp_path):
    use = bash_use("toolu_beta", DECLARED_B)
    use["session_id"] = 12345
    records = [use, bash_result("toolu_beta")]
    root = build_env(tmp_path, old={"stream_records": records})
    with pytest.raises(DelegateError, match="Malformed"):
        supplements.record_verification_supplement(OLD_RUN, str(root))
