#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / "skills" / "codex-with-cc"
SCRIPTS = WORKFLOW / "scripts"
LAUNCHER_PY = SCRIPTS / "fixed_launcher.py"
INSTALLER_PY = SCRIPTS / "install_fixed_launcher.py"
HOOK_SCRIPT = REPO / "hooks" / "subagent-gate-hook.mjs"
sys.path.insert(0, str(SCRIPTS))

from codex_with_cc_runtime.fixed_launcher import (  # noqa: E402
    LaunchError,
    build_delegate_args,
    check_descriptor_safety,
    check_paths,
    check_thread_binding,
    claim_descriptor,
    install_launcher,
    main,
    read_launch_descriptor,
    validate_descriptor,
)

TEST_TEMP_ROOT = REPO / "build" / "fixed-launcher-tests"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)


def secure_temporary_directory(*, prefix: str):
    return tempfile.TemporaryDirectory(prefix=prefix, dir=TEST_TEMP_ROOT)


def base_descriptor() -> dict:
    return {
        "version": "1.2.0",
        "invocation": "codex_with_cc_workflow",
        "childThread": {
            "threadId": "thread-a",
        },
        "projectWorkingDirectory": "/tmp/project",
        "taskFile": "./task.md",
        "workflowId": "wf-a",
        "taskId": "task-a",
        "role": "implementer",
        "sessionKey": "session-a",
    }


def run_hook(payload: dict, env: dict[str, str] | None = None) -> dict:
    base_env = _make_hook_env()
    if env:
        base_env.update(env)
    return _run_hook_impl(payload, base_env)


def _run_hook_impl(payload: dict, env: dict[str, str]) -> dict:
    result = subprocess.run(
        ["node", str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=REPO,
        encoding="utf-8",
        env=env,
        check=False,
    )
    assert result.returncode == 0, (
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    if not result.stdout.strip():
        return {}
    return json.loads(result.stdout)


def hook_specific(output: dict) -> dict:
    return output["hookSpecificOutput"]


# ---------------------------------------------------------------------------
#  Core validation tests
# ---------------------------------------------------------------------------


class TestDescriptorValidation:
    def test_rejects_bad_version(self):
        desc = base_descriptor()
        desc["version"] = "1.1.2"
        with pytest.raises(LaunchError, match="version must be"):
            validate_descriptor(desc)

    def test_rejects_bad_invocation(self):
        desc = base_descriptor()
        desc["invocation"] = "other"
        with pytest.raises(LaunchError, match="invocation must be"):
            validate_descriptor(desc)

    def test_rejects_unknown_top_level_fields(self):
        desc = base_descriptor()
        desc["extraField"] = "x"
        with pytest.raises(LaunchError, match="unknown top-level fields"):
            validate_descriptor(desc)

    def test_rejects_missing_required_fields(self):
        for key in ["taskFile", "workflowId", "taskId", "sessionKey", "projectWorkingDirectory"]:
            desc = base_descriptor()
            del desc[key]
            with pytest.raises(LaunchError, match=f"{key} is required"):
                validate_descriptor(desc)

    def test_rejects_invalid_role(self):
        desc = base_descriptor()
        desc["role"] = "manager"
        with pytest.raises(LaunchError, match="role must be one of"):
            validate_descriptor(desc)

    def test_rejects_reviewer_without_review_block(self):
        desc = base_descriptor()
        desc["role"] = "reviewer"
        with pytest.raises(LaunchError, match="review block is required"):
            validate_descriptor(desc)

    def test_rejects_review_block_for_non_reviewer(self):
        desc = base_descriptor()
        desc["review"] = {
            "reviewForTaskId": "t",
            "reviewForRunId": "r",
            "reviewKind": "spec",
        }
        with pytest.raises(LaunchError, match="review block is only allowed"):
            validate_descriptor(desc)

    def test_rejects_unknown_review_fields(self):
        desc = base_descriptor()
        desc["role"] = "reviewer"
        desc["review"] = {
            "reviewForTaskId": "t",
            "reviewForRunId": "r",
            "reviewKind": "spec",
            "extra": "nope",
        }
        with pytest.raises(LaunchError, match="unknown review fields"):
            validate_descriptor(desc)

    def test_rejects_unknown_session_fields(self):
        desc = base_descriptor()
        desc["session"] = {"sessionMode": "PrimaryReuse", "unknown": 1}
        with pytest.raises(LaunchError, match="unknown session fields"):
            validate_descriptor(desc)

    def test_rejects_unknown_child_thread_fields(self):
        desc = base_descriptor()
        desc["childThread"]["extra"] = "nope"
        with pytest.raises(LaunchError, match="unknown childThread fields"):
            validate_descriptor(desc)

    def test_rejects_non_string_scope_element(self):
        desc = base_descriptor()
        desc["scope"] = ["ok", 123]
        with pytest.raises(LaunchError, match=r"scope\[1\].*string"):
            validate_descriptor(desc)

    def test_rejects_non_string_tests_element(self):
        desc = base_descriptor()
        desc["tests"] = [456]
        with pytest.raises(LaunchError, match=r"tests\[0\].*string"):
            validate_descriptor(desc)

    def test_rejects_non_boolean_allow_parallel(self):
        desc = base_descriptor()
        desc["session"] = {"sessionMode": "PrimaryReuse", "allowParallel": "yes"}
        with pytest.raises(LaunchError, match="session.allowParallel must be boolean"):
            validate_descriptor(desc)

    def test_rejects_non_integer_max_retry(self):
        desc = base_descriptor()
        desc["maxRetryCount"] = "three"
        with pytest.raises(LaunchError, match="maxRetryCount must be an integer"):
            validate_descriptor(desc)

    @pytest.mark.parametrize("value", [True, 1.5])
    def test_rejects_boolean_or_float_integer_fields(self, value):
        desc = base_descriptor()
        desc["maxRetryCount"] = value
        with pytest.raises(LaunchError, match="maxRetryCount must be an integer"):
            validate_descriptor(desc)

    def test_rejects_integer_out_of_range(self):
        desc = base_descriptor()
        desc["executionTimeoutSeconds"] = 0
        with pytest.raises(LaunchError, match="executionTimeoutSeconds must be between 1 and 86400"):
            validate_descriptor(desc)

    def test_rejects_non_boolean_bypass_permissions(self):
        desc = base_descriptor()
        desc["bypassPermissions"] = 1
        with pytest.raises(LaunchError, match="bypassPermissions must be boolean"):
            validate_descriptor(desc)

    def test_parallel_requires_non_empty_scope(self):
        desc = base_descriptor()
        desc["session"] = {"sessionMode": "ParallelPool", "allowParallel": True}
        with pytest.raises(LaunchError, match="scope is required"):
            validate_descriptor(desc)

    def test_rejects_removed_child_fallback_alias(self):
        desc = base_descriptor()
        desc["childThread"]["fallback"] = True
        with pytest.raises(LaunchError, match="unknown childThread fields"):
            validate_descriptor(desc)


# ---------------------------------------------------------------------------
#  Thread binding tests
# ---------------------------------------------------------------------------


class TestThreadBinding:
    def test_requires_env(self):
        desc = base_descriptor()
        old = os.environ.pop("CODEX_THREAD_ID", None)
        try:
            with pytest.raises(LaunchError, match="CODEX_THREAD_ID is not set"):
                check_thread_binding(desc)
        finally:
            if old is not None:
                os.environ["CODEX_THREAD_ID"] = old

    def test_rejects_mismatch(self):
        desc = base_descriptor()
        os.environ["CODEX_THREAD_ID"] = "thread-b"
        try:
            with pytest.raises(LaunchError, match="childThread.threadId mismatch"):
                check_thread_binding(desc)
        finally:
            os.environ["CODEX_THREAD_ID"] = "thread-a"

    def test_allows_trusted_local_fallback(self):
        desc = base_descriptor()
        desc["trustedLocalFallback"] = True
        os.environ["CODEX_THREAD_ID"] = "thread-different"
        try:
            check_thread_binding(desc)
        finally:
            os.environ["CODEX_THREAD_ID"] = "thread-a"


# ---------------------------------------------------------------------------
#  Path checking tests
# ---------------------------------------------------------------------------


class TestPathChecking:
    def test_rejects_non_absolute_project_cwd(self):
        with secure_temporary_directory(prefix="cc_launch_paths_") as tmp:
            tdir = Path(tmp)
            desc = base_descriptor()
            desc["projectWorkingDirectory"] = "relative/path"
            with pytest.raises(LaunchError, match="must be absolute"):
                check_paths(desc, tdir)

    def test_rejects_missing_task_file(self):
        with secure_temporary_directory(prefix="cc_launch_paths_missing_") as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            desc = base_descriptor()
            desc["projectWorkingDirectory"] = str(project)
            desc["taskFile"] = "./missing.md"
            with pytest.raises(LaunchError, match="taskFile"):
                check_paths(desc, project.parent)

    def test_rejects_absolute_task_file(self):
        with secure_temporary_directory(prefix="cc_launch_paths_abs_") as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            desc = base_descriptor()
            desc["projectWorkingDirectory"] = str(project)
            desc["taskFile"] = "/etc/passwd"
            with pytest.raises(LaunchError, match="taskFile must be relative"):
                check_paths(desc, project.parent)

    def test_rejects_dot_dot_task_file(self):
        with secure_temporary_directory(prefix="cc_launch_dotdot_") as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            desc = base_descriptor()
            desc["projectWorkingDirectory"] = str(project)
            desc["taskFile"] = "../outside.md"
            with pytest.raises(LaunchError, match="must not contain .."):
                check_paths(desc, project.parent)

    def test_rejects_task_outside_project_root(self):
        with secure_temporary_directory(prefix="cc_launch_outside_") as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            outside = Path(tmp) / "side" / "task.md"
            outside.parent.mkdir()
            outside.write_text("# task", encoding="utf-8")
            fake_symlink = project / "lnk"
            fake_symlink.symlink_to(outside.parent, target_is_directory=True)
            desc = base_descriptor()
            desc["projectWorkingDirectory"] = str(project)
            desc["taskFile"] = "lnk/task.md"
            with pytest.raises(LaunchError, match="symlink in path"):
                check_paths(desc, project.parent)

    def test_rejects_intermediate_project_symlink(self):
        with secure_temporary_directory(prefix="cc_launch_project_link_") as tmp:
            root = Path(tmp)
            real_project = root / "real-project"
            real_project.mkdir()
            (real_project / "task.md").write_text("# task", encoding="utf-8")
            linked_project = root / "linked-project"
            linked_project.symlink_to(real_project, target_is_directory=True)
            desc = base_descriptor()
            desc["projectWorkingDirectory"] = str(linked_project)
            desc["taskFile"] = "task.md"
            with pytest.raises(LaunchError, match="symlink in path"):
                check_paths(desc)


# ---------------------------------------------------------------------------
#  Descriptor safety tests (owner, mode, symlinks)
# ---------------------------------------------------------------------------


class TestDescriptorSafety:
    def test_rejects_launch_json_as_symlink(self):
        with secure_temporary_directory(prefix="cc_desc_safe_") as tmp:
            d = Path(tmp) / "desc"
            d.mkdir()
            real = d / "real.json"
            real.write_text('{"version":"1.2.0"}', encoding="utf-8")
            link = d / "launch.json"
            link.symlink_to("real.json")
            with pytest.raises(LaunchError, match="launch.json"):
                check_descriptor_safety(d)

    def test_rejects_group_writable_descriptor_directory(self):
        with secure_temporary_directory(prefix="cc_desc_mode_") as tmp:
            descriptor_dir = Path(tmp) / "desc"
            descriptor_dir.mkdir()
            (descriptor_dir / "launch.json").write_text("{}", encoding="utf-8")
            descriptor_dir.chmod(0o770)
            try:
                with pytest.raises(LaunchError, match="group- or world-writable"):
                    check_descriptor_safety(descriptor_dir)
            finally:
                descriptor_dir.chmod(0o700)

    def test_rejects_group_writable_launch_json(self):
        with secure_temporary_directory(prefix="cc_desc_file_mode_") as tmp:
            descriptor_dir = Path(tmp) / "desc"
            descriptor_dir.mkdir()
            descriptor_file = descriptor_dir / "launch.json"
            descriptor_file.write_text("{}", encoding="utf-8")
            descriptor_file.chmod(0o660)
            with pytest.raises(LaunchError, match="group- or world-writable"):
                check_descriptor_safety(descriptor_dir)


# ---------------------------------------------------------------------------
#  Claim tests
# ---------------------------------------------------------------------------


class TestClaim:
    def test_claim_is_atomic(self):
        with secure_temporary_directory(prefix="cc_claim_") as tmp:
            desc_dir = Path(tmp)
            claim_descriptor(desc_dir)
            claimed = desc_dir / "claimed"
            assert claimed.exists()
            # mode must be owner-only (0o600)
            claim_mode = stat.S_IMODE(claimed.stat().st_mode)
            assert claim_mode == 0o600, f"claim mode is {oct(claim_mode)}"
            with pytest.raises(LaunchError, match="already been claimed"):
                claim_descriptor(desc_dir)

    def test_two_independent_directories_work_concurrently(self):
        with secure_temporary_directory(prefix="cc_concurrent_") as parent:
            for name in ("a", "b"):
                desc_dir = Path(parent) / name
                desc_dir.mkdir()
                desc = base_descriptor()
                desc["childThread"]["threadId"] = name
                (desc_dir / "launch.json").write_text(json.dumps(desc), encoding="utf-8")

            for name in ("a", "b"):
                desc_dir = Path(parent) / name
                os.environ["CODEX_THREAD_ID"] = name
                read = read_launch_descriptor(desc_dir)
                validate_descriptor(read)
                check_thread_binding(read)
                claim_descriptor(desc_dir)

            for name in ("a", "b"):
                assert (Path(parent) / name / "claimed").exists()


# ---------------------------------------------------------------------------
#  Installer tests
# ---------------------------------------------------------------------------


class TestInstaller:
    def test_is_idempotent(self):
        with secure_temporary_directory(prefix="cc_install_") as tmp:
            codex_home = Path(tmp) / "codex-home"
            codex_home.mkdir()
            launcher = install_launcher(codex_home)
            assert launcher.exists()
            assert os.access(launcher, os.X_OK)
            assert "codex-with-cc-launch" in launcher.name
            first_content = launcher.read_text(encoding="utf-8")
            launcher2 = install_launcher(codex_home)
            assert launcher2 == launcher
            assert launcher2.read_text(encoding="utf-8") == first_content

    def test_atomic_write_preserves_filename(self):
        with secure_temporary_directory(prefix="cc_install_atomic_") as tmp:
            codex_home = Path(tmp) / "codex-home"
            codex_home.mkdir()
            launcher = install_launcher(codex_home)
            assert launcher.name == "codex-with-cc-launch"
            # No temp files left behind
            bin_dir = codex_home / "bin"
            leftovers = list(bin_dir.glob(".tmp-*"))
            assert len(leftovers) == 0, leftovers

    def test_embeds_sys_executable_not_arbitrary_python3(self):
        with secure_temporary_directory(prefix="cc_install_pyexe_") as tmp:
            codex_home = Path(tmp) / "codex-home"
            codex_home.mkdir()
            launcher = install_launcher(codex_home)
            text = launcher.read_text(encoding="utf-8")
            assert f"exec {Path(sys.executable).resolve()}" in text
            assert "exec python3 " not in text

    def test_embeds_current_workflow_root(self):
        with secure_temporary_directory(prefix="cc_install_root_") as tmp:
            codex_home = Path(tmp) / "codex-home"
            codex_home.mkdir()
            launcher = install_launcher(codex_home)
            text = launcher.read_text(encoding="utf-8")
            assert str(WORKFLOW) in text
            assert "fixed_launcher.py" in text

    def test_rejects_codex_home_not_owned_by_user(self, monkeypatch):
        with secure_temporary_directory(prefix="cc_install_notowner_") as tmp:
            codex_home = Path(tmp) / "codex-home"
            codex_home.mkdir()
            # Fake UID to simulate ownership failure
            monkeypatch.setattr(os, "getuid", lambda: 99999)
            with pytest.raises(LaunchError, match="not owned by current user"):
                install_launcher(codex_home)


# ---------------------------------------------------------------------------
#  Hook tests
# ---------------------------------------------------------------------------


_canonical_bare = "/Users/test/.codex/bin/codex-with-cc-launch"


def _make_hook_env(thread_id: str = "thread-a") -> dict:
    return {
        **os.environ,
        "CODEX_HOME": "/Users/test/.codex",
        "HOME": "/Users/test",
        "CODEX_THREAD_ID": thread_id,
    }


class TestHook:
    def test_allows_exact_zsh_wrapped_launcher(self):
        output = run_hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": '/bin/zsh -c "/Users/test/.codex/bin/codex-with-cc-launch"'},
        })
        assert output == {}

    def test_allows_bare_launcher(self):
        output = run_hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": _canonical_bare},
        })
        assert output == {}

    def test_denies_launcher_with_arguments(self):
        output = run_hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": f"{_canonical_bare} --extra"},
        })
        reason = hook_specific(output)["permissionDecisionReason"]
        assert "stable command shape" in reason

    def test_denies_variable_path_in_zsh_wrapper(self):
        output = run_hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": '/bin/zsh -c "$HOME/.codex/bin/codex-with-cc-launch"'},
        })
        reason = hook_specific(output)["permissionDecisionReason"]
        assert "stable command shape" in reason

    def test_denies_same_basename_different_path(self):
        output = run_hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "/tmp/evil/codex-with-cc-launch"},
        })
        reason = hook_specific(output)["permissionDecisionReason"]
        assert "stable command shape" in reason

    def test_denies_chained_read_only_with_launcher(self):
        # rg first, then launcher after semicolon
        output = run_hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": f'rg -n "launch" file.txt; {_canonical_bare}'},
        })
        reason = hook_specific(output)["permissionDecisionReason"]
        assert "stable command shape" in reason

    def test_allows_pure_read_only_search_mentioning_launcher(self):
        output = run_hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": 'rg -n "codex-with-cc-launch" docs/fixed-launcher.md'},
        })
        assert output == {}

    def test_denies_chained_starting_with_read_only(self):
        # cat ...; codex-with-cc-launch
        output = run_hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": f'cat file.txt; {_canonical_bare}'},
        })
        reason = hook_specific(output)["permissionDecisionReason"]
        assert "stable command shape" in reason

    @pytest.mark.parametrize("command", [
        "\n/Users/test/.codex/bin/codex-with-cc-launch",
        "/Users/test/.codex/bin/codex-with-cc-launch ",
        '/bin/zsh -c "/Users/test/.codex/bin/codex-with-cc-launch"\n',
    ])
    def test_denies_whitespace_variants(self, command):
        output = run_hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
        })
        reason = hook_specific(output)["permissionDecisionReason"]
        assert "stable command shape" in reason

    def test_still_denies_direct_claude(self):
        output = run_hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": 'claude -p "do work"'},
        })
        reason = hook_specific(output)["permissionDecisionReason"]
        assert "direct Claude CLI" in reason

    def test_still_denies_legacy_delegate_without_child_marker(self):
        output = run_hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {
                "command": (
                    "pwsh -NoProfile -File windows_scripts/delegate_to_claude.ps1 "
                    "-TaskFile t.md -WorkflowId wf -TaskId task -Role researcher -SessionKey k"
                )
            },
        })
        reason = hook_specific(output)["permissionDecisionReason"]
        assert "CODEX_CLAUDE_CHILD_THREAD=1" in reason

    def test_still_allows_read_only_search_of_legacy_name(self):
        output = run_hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": 'rg -n "delegate_to_claude" README.md'},
        })
        assert output == {}

    def test_chained_read_only_cannot_bypass_legacy_delegate_gate(self):
        output = run_hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {
                "command": (
                    'rg -n "runner" README.md && '
                    "skills/codex-with-cc/macos_scripts/delegate_to_claude.sh"
                )
            },
        })
        reason = hook_specific(output)["permissionDecisionReason"]
        assert "CODEX_CLAUDE_CHILD_THREAD=1" in reason

    def test_readable_spawn_payload_supports_fixed_launcher(self):
        output = run_hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "spawn_agent",
            "tool_input": {
                "message": (
                    "Set the terminal working directory to the directory containing "
                    "launch.json and run /Users/test/.codex/bin/codex-with-cc-launch"
                ),
                "fork_context": False,
            },
        })
        assert output == {}


# ---------------------------------------------------------------------------
#  Launcher invocation tests
# ---------------------------------------------------------------------------


class TestLauncherInvocation:
    def test_enforces_no_arguments(self):
        with secure_temporary_directory(prefix="cc_noargs_") as tmp:
            result = subprocess.run(
                [sys.executable, str(LAUNCHER_PY), "--help"],
                cwd=tmp,
                text=True,
                capture_output=True,
                check=False,
            )
            assert result.returncode == 2
            assert "no command-line arguments" in result.stderr

    def test_requires_launch_json(self):
        with secure_temporary_directory(prefix="cc_missing_json_") as tmp:
            result = subprocess.run(
                [sys.executable, str(LAUNCHER_PY)],
                cwd=tmp,
                text=True,
                capture_output=True,
                check=False,
                env={**os.environ, "CODEX_THREAD_ID": "thread-a"},
            )
            assert result.returncode == 1
            assert "launch.json" in result.stderr


# ---------------------------------------------------------------------------
#  Delegate args tests
# ---------------------------------------------------------------------------


class TestBuildDelegateArgs:
    def test_maps_basic_fields(self):
        desc = base_descriptor()
        desc["scope"] = ["src"]
        desc["tests"] = ["pytest -q"]
        args = build_delegate_args(desc)
        assert args[0] == "delegate"
        assert "-TaskFile" in args and "./task.md" in args
        assert "-WorkflowId" in args and "wf-a" in args
        assert "-TaskId" in args and "task-a" in args
        assert "-Role" in args and "implementer" in args
        assert "-SessionKey" in args and "session-a" in args
        assert "-Scope" in args and "src" in args
        assert "-Tests" in args and "pytest -q" in args

    def test_includes_reviewer_metadata(self):
        desc = base_descriptor()
        desc["role"] = "reviewer"
        desc["review"] = {
            "reviewForTaskId": "impl-task",
            "reviewForRunId": "run-1",
            "reviewKind": "quality",
        }
        args = build_delegate_args(desc)
        assert "-ReviewForTaskId" in args
        assert "impl-task" in args
        assert "-ReviewKind" in args and "quality" in args

    def test_includes_session_mode_and_parallel(self):
        desc = base_descriptor()
        desc["session"] = {"sessionMode": "ParallelPool", "allowParallel": True}
        args = build_delegate_args(desc)
        assert "-SessionMode" in args and "ParallelPool" in args
        assert "-AllowParallel" in args

    def test_includes_timeout_and_retry_fields(self):
        desc = base_descriptor()
        desc["executionTimeoutSeconds"] = 120
        desc["maxRetryCount"] = 2
        desc["heartbeatSeconds"] = 10
        args = build_delegate_args(desc)
        assert "-ExecutionTimeoutSeconds" in args and "120" in args
        assert "-MaxRetryCount" in args and "2" in args
        assert "-HeartbeatSeconds" in args and "10" in args

    def test_includes_dry_run_and_trusted_fallback(self):
        desc = base_descriptor()
        desc["dryRun"] = True
        desc["trustedLocalFallback"] = True
        args = build_delegate_args(desc)
        assert "-DryRun" in args
        assert "-TrustedLocalFallback" in args

    def test_includes_model_and_budget(self):
        desc = base_descriptor()
        desc["model"] = "sonnet"
        desc["maxBudgetUsd"] = "5.00"
        args = build_delegate_args(desc)
        assert "-Model" in args and "sonnet" in args
        assert "-MaxBudgetUsd" in args and "5.00" in args

    def test_includes_artifact_root_and_output_path(self):
        desc = base_descriptor()
        desc["artifactRoot"] = "/tmp/artifacts"
        desc["outputPath"] = "/tmp/out.md"
        args = build_delegate_args(desc)
        assert "-ArtifactRoot" in args and "/tmp/artifacts" in args
        assert "-OutputPath" in args and "/tmp/out.md" in args

    def test_includes_lock_and_session_params(self):
        desc = base_descriptor()
        desc["lockTimeoutSeconds"] = 60
        desc["sessionLeaseTimeoutSeconds"] = 7200
        args = build_delegate_args(desc)
        assert "-LockTimeoutSeconds" in args and "60" in args
        assert "-SessionLeaseTimeoutSeconds" in args and "7200" in args


# ---------------------------------------------------------------------------
#  End-to-end (dry-run) test
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_fake_delegate_dry_run(self):
        with secure_temporary_directory(prefix="cc_e2e_") as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            tasks = project / ".codex" / "codex_with_cc" / "tasks"
            tasks.mkdir(parents=True)
            task_file = tasks / "task.md"
            task_file.write_text(
                """# Contract Driven Task

Goal
Inspect the fixed launcher end-to-end path.

Allowed Scope
- skills/codex-with-cc

Forbidden Actions
- Do not edit README.md.
- Do not invoke nested delegate runs.

Acceptance Criteria
- The launcher reaches the delegate runtime.

Verification
- dry-run artifact generation completed

Report Requirements
- Status / Role / Summary / Changed Files / Verification / Findings / Final Result / Risks Or Follow-ups
""",
                encoding="utf-8",
            )
            launch_dir = project / ".codex" / "codex_with_cc" / "launcher-runs" / "wf-a" / "task-a"
            launch_dir.mkdir(parents=True)
            desc = base_descriptor()
            desc["projectWorkingDirectory"] = str(project)
            desc["taskFile"] = str(task_file.relative_to(project))
            desc["dryRun"] = True
            (launch_dir / "launch.json").write_text(json.dumps(desc), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(LAUNCHER_PY)],
                cwd=str(launch_dir),
                text=True,
                capture_output=True,
                check=False,
                env={**os.environ, "CODEX_THREAD_ID": "thread-a", "PYTHONDONTWRITEBYTECODE": "1"},
            )
            assert result.returncode == 0, result.stdout + result.stderr
            assert (launch_dir / "claimed").exists()


# ---------------------------------------------------------------------------
#  main() argument rejection test
# ---------------------------------------------------------------------------


class TestMain:
    def test_exits_nonzero_for_arguments(self, monkeypatch):
        with secure_temporary_directory(prefix="cc_main_args_") as tmp:
            monkeypatch.chdir(tmp)
            assert main(["--help"]) == 2
