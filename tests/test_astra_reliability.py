from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/codex-with-cc/scripts"))
from codex_with_cc_runtime import artifacts, workflow, run_health
from codex_with_cc_runtime.common import DelegateError
from tests.test_platform_hooks import run_hook, hook_specific


def test_empty_workflow_cannot_be_verified(tmp_path):
    w = workflow.empty_workflow("empty")
    workflow.update_workflow_acceptance(w)
    assert w["finalAcceptance"]["status"] == "pending-run"
    w["finalAcceptance"] = {"status": "accepted"}
    workflow.workflow_path(tmp_path, "empty").write_text(json.dumps(w))
    with pytest.raises(DelegateError, match="empty workflows"):
        artifacts.run_verify_workflow(argparse.Namespace(workflow_id="empty", artifact_root=str(tmp_path)))


@pytest.mark.parametrize("command", [
    "claude --version", "claude --help", "claude auth status",
    "env FOO=bar claude --version", "command claude --version",
    "pwd && cat ~/.codex/bin/codex-with-cc-launch",
    "sed -n '1,30p' ~/.codex/bin/codex-with-cc-launch\ncat README.md",
    "rg -n codex-with-cc-launch hooks | head -n 10",
    "git diff && rg delegate_to_claude README.md",
    "cat ~/.codex/bin/codex-with-cc-launch; touch /tmp/x",
])
def test_diagnostics_and_batched_reads(command):
    assert run_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}}) == {}


@pytest.mark.parametrize("command", [
    "claude --version && claude -p hello", "claude --help --print hello",
    "claude auth login", "claude --version; env FOO=1 claude -p hello",
    "sed -i '' x ~/.codex/bin/codex-with-cc-launch",
    "cat ~/.codex/bin/codex-with-cc-launch | bash",
    "sed -n 'e claude -p hello' ~/.codex/bin/codex-with-cc-launch",
    "rg --pre='claude -p hello' codex-with-cc-launch README.md",
])
def test_diagnostics_do_not_allow_execution(command):
    assert hook_specific(run_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}}))["permissionDecision"] == "deny"


def test_health_does_not_rewrite_or_accept_abandoned_run(tmp_path, monkeypatch):
    p = tmp_path / "status_run.json"
    p.write_text(json.dumps({"runId": "run", "status": "running", "pid": 12345}))
    before = p.read_bytes()
    def dead(pid, sig):
        raise ProcessLookupError(pid)
    monkeypatch.setattr(os, "kill", dead)
    assert run_health.inspect_runs(tmp_path)[0]["observedStatus"] == "abandoned"
    assert p.read_bytes() == before


def test_interrupted_report_cannot_recover_to_completed(tmp_path):
    (tmp_path / "config_run.json").write_text("{}")
    (tmp_path / "status_run.json").write_text('{"status":"interrupted"}')
    with pytest.raises(DelegateError, match="interrupted"):
        artifacts.verify_artifacts("run", str(tmp_path))


@pytest.mark.skipif(os.name != "posix", reason="POSIX signal integration")
def test_signal_records_interruption_and_terminates_fake_worker(tmp_path):
    import subprocess
    import time
    from tests.task_helpers import compliant_task
    scripts = Path(__file__).resolve().parents[1] / "skills/codex-with-cc/scripts"
    fake = tmp_path / "bin"
    fake.mkdir()
    executable = fake / "claude"
    executable.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(60)\n")
    executable.chmod(0o755)
    task = tmp_path / "task.md"
    task.write_text(compliant_task("Read fixture contents and report findings."))
    root = tmp_path / "artifacts"
    env = {**os.environ, "PATH": str(fake) + os.pathsep + os.environ.get("PATH", ""), "CODEX_CLAUDE_CHILD_THREAD": "1"}
    process = subprocess.Popen([sys.executable, str(scripts / "runtime.py"), "delegate", "-TaskFile", str(task),
        "-WorkflowId", "interruption", "-TaskId", "task", "-Role", "researcher", "-SessionKey", "signal-test",
        "-ArtifactRoot", str(root), "-TrustedLocalFallback"], cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 8
        status_file = None
        while time.monotonic() < deadline:
            paths = list(root.glob("status_*.json"))
            if paths and json.loads(paths[0].read_text()).get("status") == "running":
                status_file = paths[0]
                break
            if process.poll() is not None:
                break
            time.sleep(.03)
        assert status_file is not None
        process.terminate()
        process.communicate(timeout=8)
        status = json.loads(status_file.read_text())
        assert status["status"] == "interrupted"
        assert status["exitCode"] != 0
        w = json.loads(next(root.glob("workflow_*.json")).read_text())
        assert w["finalAcceptance"]["status"] != "accepted"
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
