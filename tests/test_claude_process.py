"""Offline real-process tests. The fixture executable never calls a model/provider."""
import json
import os
import sys
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests.test_execution_profiles import project, run, checks, main_review
from tests.test_adaptive_cc import adaptive, prepare, verify
from tests.test_workflow_contract import workflow_report
from tests.test_platform_hooks import run_hook
from codex_with_cc_runtime import fixed_launcher, lifecycle, workflow
from codex_with_cc_runtime.artifacts import verify_artifacts
from codex_with_cc_runtime.common import DelegateError, now_iso
from codex_with_cc_runtime.io_utils import load_json
from codex_with_cc_runtime.metrics import workflow_metrics
from codex_with_cc_runtime.process_permissions import allowed_commands, authorize_tool, permission_hook
from codex_with_cc_runtime.process_run import process_cli, validate_process_launch, verify_launch_evidence
from codex_with_cc_runtime.routing import verified_plan, spawn_payload


@pytest.fixture
def process_project(project, monkeypatch):
    p, root = project
    adaptive(project, monkeypatch, 1)
    caps = root / "process-caps.json"
    caps.write_text(json.dumps({"schemaVersion": 1, "source": "active-tool-catalog", "tools": ["functions.exec", "exec_command", "write_stdin"]}))
    runtime = Path(__file__).resolve().parents[1] / "skills/codex-with-cc/scripts/runtime.py"
    subprocess.run([sys.executable, str(runtime), "configure-lifecycle", "-WorkflowId", "new", "-ArtifactRoot", str(root),
                    "-Policy", "process-exit", "-HostToolsFile", str(caps)], cwd=p, check=True, capture_output=True, text=True)
    binary = p / "bin"
    binary.mkdir()
    executable = binary / "claude"
    report = workflow_report(role="implementer").replace("dry run artifact generation passed", "python3 check.py: 8 cases passed")
    executable.write_text("#!" + sys.executable + "\n" + '''import json, os, sys, time
sys.stdin.read()
time.sleep(float(os.environ.get("PROCESS_FIXTURE_SLEEP", "0")))
record = {"type":"result", "subtype":"success", "result":''' + repr(report) + '''}
if os.environ.get("PROCESS_FIXTURE_DENY"):
    record["permission_denials"] = [{"tool_name":"Bash", "tool_input":{"command":"python3 -c forbidden"}}]
print(json.dumps(record), flush=True)
''')
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(binary) + os.pathsep + os.environ["PATH"])
    (p / "check.py").write_text("print('8 cases passed')\n")
    commands = root / "commands.json"
    commands.write_text(json.dumps({"schemaVersion": 1, "commands": [{"argv": ["python3", "check.py"], "pinnedFiles": ["check.py"]}]}))
    return project, commands


def prepared(fixture, *extra, tid="impl"):
    project, commands = fixture
    return prepare(project, tid, "implementer", "app.py", "-Backend", "claude-process", "-AllowedCommandsFile", str(commands), *extra)


def launch(path, monkeypatch):
    original = Path.cwd()
    try:
        monkeypatch.chdir(path.parent)
        return fixed_launcher.main([])
    finally:
        monkeypatch.chdir(original)


def latest(project):
    w = load_json(workflow.workflow_path(project[1], "new"))
    rid = list(w["processAttempts"])[-1]
    return w, rid, load_json(project[1] / f"status_{rid}.json")


def test_real_process_standard_acceptance_and_no_carrier(process_project, monkeypatch):
    project, _ = process_project
    path = prepared(process_project, "-Admit")
    p = load_json(path)
    payload = spawn_payload(path, p)
    assert "spawn" not in payload and payload["launch"]["workdir"] == str(path.parent)
    assert p["model"] is None and p["workerModel"] == "sonnet"
    assert launch(path, monkeypatch) == 0
    w, rid, status = latest(project)
    assert status["pid"] > 0 and status["processGroupExited"] and status["exitCode"] == 0
    assert not w["agentAttempts"] and w["processAttempts"][rid]["settledAt"]
    verified = verify_artifacts(rid, str(project[1]))
    assert "codexThreadId" not in verified["config"] and "childThreadMarkerValidated" not in verified["config"]
    assert workflow_metrics(project[1], w)["hostThreads"] == []
    assert main_review(project, monkeypatch, checks(project)) == 0
    assert verify(project) == 0
    with pytest.raises(DelegateError, match="claimed"):
        launch(path, monkeypatch)


def test_permissions_exact_command_and_scope(process_project):
    p = load_json(prepared(process_project, "-Admit"))
    def decision(command):
        return authorize_tool(p, {"tool_name": "Bash", "tool_input": {"command": command}})[0]
    assert decision("python3 check.py")
    assert authorize_tool(p, {"tool_name": "StructuredOutput", "tool_input": {"status": "DONE"}})[0]
    for command in ("python3", "python3 -c print(1)", "python3 check.py extra", "python3 check.py; id", "python3 check.py && id", "$(python3 check.py)", "python3 check.py\n", "cd . && python3 check.py"):
        assert not decision(command)
    assert authorize_tool(p, {"tool_name": "Write", "tool_input": {"file_path": "app.py"}})[0]
    assert not authorize_tool(p, {"tool_name": "Write", "tool_input": {"file_path": "other.py"}})[0]
    p["role"] = "researcher"
    assert not authorize_tool(p, {"tool_name": "Write", "tool_input": {"file_path": "app.py"}})[0]
    argv = process_cli(p, Path(p["taskFile"]).parent / "plan.json", "fixture")
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert "Bash(python3 check.py)" in argv and "bypassPermissions" not in argv
    assert "StructuredOutput" in argv
    assert "--json-schema" in argv  # Reporting tool is injected by the schema, not a builtin --tools capability.


@pytest.mark.parametrize("argv", [["bash", "check.py"], ["python3", "-c", "print(1)"], ["python3"], ["git", "status;id"], ["echo", "$(id)"], ["git", "*"]])
def test_unsafe_command_authorizations_rejected(process_project, argv):
    project, commands = process_project
    commands.write_text(json.dumps({"schemaVersion": 1, "commands": [{"argv": argv}]}))
    with pytest.raises(DelegateError):
        allowed_commands(str(commands), project[0])


def test_script_pin_rechecked_at_tool_time_and_launch(process_project):
    path = prepared(process_project, "-Admit")
    (process_project[0][0] / "check.py").write_text("raise Exception('changed')\n")
    with pytest.raises(DelegateError, match="content changed"):
        validate_process_launch(path.parent)
    result = permission_hook(path, {"tool_name": "Bash", "tool_input": {"command": "python3 check.py"}})
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize("which", ["plan", "descriptor", "provider", "host"])
def test_prelaunch_tampering_refused(process_project, monkeypatch, which):
    path = prepared(process_project, "-Admit")
    if which == "plan":
        path.write_text(path.read_text().replace('"workerEffort": "high"', '"workerEffort": "low"'))
    elif which == "descriptor":
        (path.parent / "launch.json").write_text('{}')
    elif which == "provider":
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://changed.invalid")
    else:
        monkeypatch.setenv("CODEX_THREAD_ID", "some-child")
    with pytest.raises(DelegateError):
        launch(path, monkeypatch)
    assert not (path.parent / "claimed").exists()


@pytest.mark.parametrize("changed", ["stream", "status", "receipt", "report"])
def test_original_process_artifact_tampering_rejected(process_project, monkeypatch, changed):
    project, _ = process_project
    path = prepared(process_project, "-Admit")
    assert launch(path, monkeypatch) == 0
    w, rid, _ = latest(project)
    config = load_json(project[1] / f"config_{rid}.json")
    target = {"stream": config["rawStreamPath"], "status": str(project[1] / f"status_{rid}.json"), "receipt": config["receiptPath"], "report": config["outputPath"]}[changed]
    with Path(target).open("a") as stream:
        stream.write("\n")
    with pytest.raises(DelegateError, match="changed"):
        verify_artifacts(rid, str(project[1]))


def test_timeout_cleanup_settles_failure_and_releases_capacity(process_project, monkeypatch):
    project, _ = process_project
    path = prepared(process_project, "-ExecutionTimeoutSeconds", "1", "-Admit")
    next_path = prepared(process_project, tid="next")
    with pytest.raises(DelegateError, match="concurrency"):
        run("admit-task", "-PlanFile", str(next_path))
    monkeypatch.setenv("PROCESS_FIXTURE_SLEEP", "10")
    assert launch(path, monkeypatch) == 124
    w, rid, status = latest(project)
    assert status["failureReason"] == "execution-timeout" and status["processGroupExited"]
    assert w["processAttempts"][rid]["settledAt"]
    assert verify_artifacts(rid, str(project[1]))["status"]["status"] == "failed"
    assert run("admit-task", "-PlanFile", str(next_path)) == 0


def test_permission_denial_is_failure_even_with_done_report(process_project, monkeypatch):
    path = prepared(process_project, "-Admit")
    monkeypatch.setenv("PROCESS_FIXTURE_DENY", "1")
    assert launch(path, monkeypatch) == 1
    _, _, status = latest(process_project[0])
    assert status["failureReason"] == "permission-denied" and status["status"] == "failed"


def test_process_dependencies_wait_for_settlement(process_project, monkeypatch):
    project, _ = process_project
    first = prepared(process_project, "-Admit")
    child = prepared(process_project, "-DependsOn", "impl", tid="dependent")
    with pytest.raises(DelegateError, match="dependency"):
        run("admit-task", "-PlanFile", str(child))
    assert launch(first, monkeypatch) == 0
    assert run("admit-task", "-PlanFile", str(child)) == 0


def test_original_main_launch_call_is_hash_bound(process_project, monkeypatch):
    path = prepared(process_project, "-Admit")
    p = load_json(path)
    log = Path(p["mainHost"]["path"])
    call = {"type": "response_item", "timestamp": now_iso(), "payload": {"type": "custom_tool_call", "name": "functions.exec", "call_id": "actual-fixture-call",
            "input": "await tools.exec_command(" + json.dumps(spawn_payload(path, p)["launch"]) + ");"}}
    with log.open("a") as stream:
        stream.write(json.dumps(call) + "\n")
    assert launch(path, monkeypatch) == 0
    _, rid, _ = latest(process_project[0])
    config = load_json(process_project[0][1] / f"config_{rid}.json")
    evidence = config["mainLaunchEvidence"]
    assert evidence["status"] == "original-main-tool-call"
    verify_launch_evidence(evidence)
    log.write_text(log.read_text().replace("actual-fixture-call", "changed-fixture-call"))
    with pytest.raises(DelegateError, match="launch evidence changed"):
        verify_launch_evidence(evidence)


def test_real_permission_hook_protocol_and_pinned_script_execution(process_project):
    path = prepared(process_project, "-Admit")
    project, _ = process_project
    hook = Path(__file__).resolve().parents[1] / "skills/codex-with-cc/scripts/process_permission_hook.py"
    event = {"cwd": str(project[0]), "tool_name": "Bash", "tool_input": {"command": "python3 check.py"}}
    result = subprocess.run([sys.executable, str(hook), str(path)], input=json.dumps(event), text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "allow"
    check = subprocess.run(["python3", "check.py"], cwd=project[0], capture_output=True, text=True, check=True)
    assert check.stdout.strip() == "8 cases passed"
    event["tool_input"]["command"] += "; echo unauthorized"
    result = subprocess.run([sys.executable, str(hook), str(path)], input=json.dumps(event), text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_claim_is_atomic_under_competing_launches(process_project):
    path = prepared(process_project, "-Admit")
    def claim():
        try:
            fixed_launcher.claim_descriptor(path.parent)
            return "claimed"
        except DelegateError:
            return "refused"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    assert sorted(results) == ["claimed", "refused"]


def test_process_scope_conflict_and_original_child_identity_rejected(process_project, monkeypatch):
    project, _ = process_project
    first = prepared(process_project, "-Admit", "-AllowParallel")
    second = prepared(process_project, "-AllowParallel", tid="conflict")
    with pytest.raises(DelegateError, match="scope"):
        run("admit-task", "-PlanFile", str(second))
    p = load_json(first)
    host = Path(p["mainHost"]["path"])
    host.write_text(json.dumps({"type": "session_meta", "payload": {"id": "main", "cwd": str(project[0]),
        "source": {"subagent": {"thread_spawn": {"parent_thread_id": "parent"}}}}}) + "\n")
    with pytest.raises(DelegateError, match="subagent"):
        validate_process_launch(first.parent)


def test_process_parallel_serial_retry_retains_original_receipts(process_project, monkeypatch):
    project, _ = process_project
    first = prepared(process_project, "-Admit", "-AllowParallel")
    assert launch(first, monkeypatch) == 0
    _, first_id, _ = latest(project)
    second = prepared(process_project, "-Admit", "-AllowParallel")
    assert launch(second, monkeypatch) == 0
    w, second_id, _ = latest(project)
    from codex_with_cc_runtime.parallel_scope_evidence import prove_serial_same_task
    prove_serial_same_task(project[1], w, "impl", first_id, second_id)
    assert main_review(project, monkeypatch, checks(project)) == 0
    assert verify(project) == 0


def test_installed_launcher_and_policy_hook_entrypoint(process_project, monkeypatch):
    project, _ = process_project
    path = prepared(process_project, "-Admit")
    payload = spawn_payload(path, load_json(path))["launch"]
    fixed_launcher.install_launcher()
    hook_input = {"hook_event_name": "PreToolUse", "tool_name": "exec_command", "tool_input": payload}
    assert run_hook(hook_input) == {}
    result = subprocess.run([payload["cmd"]], cwd=payload["workdir"], text=True, capture_output=True, check=True)
    packet = json.loads(result.stdout)
    assert packet["settled"] and packet["backend"] == "claude-process"
    assert len(result.stdout) < 8000
    assert run_hook(hook_input)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert verify_artifacts(packet["runId"], str(project[1]))["status"]["status"] == "completed"


def test_hook_rejects_changed_main_and_plan(process_project, monkeypatch):
    path = prepared(process_project, "-Admit")
    payload = {"hook_event_name": "PreToolUse", "tool_name": "exec_command", "tool_input": spawn_payload(path, load_json(path))["launch"]}
    assert run_hook(payload) == {}
    monkeypatch.setenv("CODEX_THREAD_ID", "different")
    assert run_hook(payload)["hookSpecificOutput"]["permissionDecision"] == "deny"
    monkeypatch.setenv("CODEX_THREAD_ID", "main")
    path.write_text(path.read_text().replace('"executionTimeoutSeconds": 900', '"executionTimeoutSeconds": 901'))
    assert run_hook(payload)["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize("backend", ["claude-code", "codex-native"])
@pytest.mark.parametrize("option", ["commands", "timeout"])
def test_process_only_options_are_not_silently_ignored(process_project, backend, option):
    project, commands = process_project
    extra = ("-AllowedCommandsFile", str(commands)) if option == "commands" else ("-ExecutionTimeoutSeconds", "2")
    with pytest.raises(DelegateError, match="requires claude-process"):
        prepare(project, "legacy", "researcher", "app.py", "-Backend", backend, *extra)
