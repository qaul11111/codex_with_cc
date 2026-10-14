from __future__ import annotations

import json
import os
import shlex
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

from .common import CHILD_MARKER_NAME, CHILD_MARKER_VALUE, DelegateError, WORKER_ROLES


LAUNCH_SCHEMA_VERSION = "1.2.0"
ALLOWED_INVOCATION = "codex_with_cc_workflow"
ALLOWED_ROLES = set(WORKER_ROLES)
ALLOWED_SESSION_MODES = {"PrimaryReuse", "PrimaryAnchor", "ParallelPool"}
ALLOWED_REVIEW_KINDS = {"spec", "quality"}


class LaunchError(DelegateError):
    pass


def _absolute_without_resolving(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return Path.cwd() / expanded


def _path_components(path: Path) -> list[Path]:
    absolute = _absolute_without_resolving(path)
    current = Path(absolute.anchor)
    components = [current]
    for part in absolute.parts[1:]:
        current = current / part
        components.append(current)
    return components


def _lstat(path: Path, label: str) -> os.stat_result:
    try:
        return path.lstat()
    except OSError as exc:
        raise LaunchError(f"{label}: cannot lstat {path}: {exc}") from exc


def _check_no_symlink_components(path: Path, label: str) -> None:
    for component in _path_components(path):
        mode = _lstat(component, label).st_mode
        if stat.S_ISLNK(mode):
            raise LaunchError(f"{label}: symlink in path: {component}")


def _check_owned_mode(path: Path, label: str, *, kind: str) -> os.stat_result:
    info = _lstat(path, label)
    if stat.S_ISLNK(info.st_mode):
        raise LaunchError(f"{label}: symlink is not allowed: {path}")
    if kind == "directory" and not stat.S_ISDIR(info.st_mode):
        raise LaunchError(f"{label}: not a directory: {path}")
    if kind == "file" and not stat.S_ISREG(info.st_mode):
        raise LaunchError(f"{label}: not a regular file: {path}")
    if info.st_uid != os.getuid():
        raise LaunchError(
            f"{label}: not owned by current user "
            f"(uid={os.getuid()}, owner_uid={info.st_uid}): {path}"
        )
    mode = stat.S_IMODE(info.st_mode)
    if mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise LaunchError(f"{label}: group- or world-writable ({mode:o}): {path}")
    return info


def _check_secure_directory(path: Path, label: str) -> None:
    _check_no_symlink_components(path, label)
    _check_owned_mode(path, label, kind="directory")


def _resolve_codex_home(codex_home: Path | str | None = None) -> Path:
    if codex_home is not None:
        selected = Path(codex_home)
    else:
        configured = os.environ.get("CODEX_HOME", "").strip()
        selected = Path(configured) if configured else Path.home() / ".codex"
    return _absolute_without_resolving(selected)


def install_launcher(codex_home: Path | str | None = None) -> Path:
    """Atomically install the stable, no-argument launcher."""
    if sys.version_info < (3, 9):
        raise LaunchError("Python 3.9+ is required")

    home = _resolve_codex_home(codex_home)
    try:
        home.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        raise LaunchError(f"CODEX_HOME: cannot create {home}: {exc}") from exc
    _check_secure_directory(home, "CODEX_HOME")

    bin_dir = home / "bin"
    try:
        bin_dir.mkdir(mode=0o700, exist_ok=True)
    except OSError as exc:
        raise LaunchError(f"CODEX_HOME/bin: cannot create {bin_dir}: {exc}") from exc
    _check_secure_directory(bin_dir, "CODEX_HOME/bin")

    try:
        python_executable = Path(sys.executable).resolve(strict=True)
    except OSError as exc:
        raise LaunchError(f"Python executable cannot be resolved: {sys.executable}: {exc}") from exc
    if not python_executable.is_file() or not os.access(python_executable, os.X_OK):
        raise LaunchError(f"Python executable is not executable: {python_executable}")

    workflow_root = Path(__file__).resolve().parents[2]
    runtime_entrypoint = workflow_root / "scripts" / "fixed_launcher.py"
    if not runtime_entrypoint.is_file():
        raise LaunchError(f"Fixed launcher runtime is missing: {runtime_entrypoint}")

    launcher = bin_dir / "codex-with-cc-launch"
    content = f"""#!/bin/zsh
set -euo pipefail

if [[ $# -ne 0 ]]; then
  print -u2 "codex-with-cc-launch: takes no command-line arguments"
  exit 2
fi

exec {shlex.quote(str(python_executable))} {shlex.quote(str(runtime_entrypoint))}
"""

    temporary: Path | None = None
    try:
        fd, temporary_name = tempfile.mkstemp(
            dir=str(bin_dir),
            prefix=".codex-with-cc-launch-",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o700)
        os.replace(temporary, launcher)
        temporary = None
        directory_fd = os.open(str(bin_dir), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise LaunchError(f"Installer atomic write failed: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass

    _check_owned_mode(launcher, "installed launcher", kind="file")
    if not os.access(launcher, os.X_OK):
        raise LaunchError(f"Installed launcher is not executable: {launcher}")
    return launcher


def _require_string(container: dict[str, Any], key: str, problems: list[str]) -> str | None:
    if key not in container:
        problems.append(f"{key} is required")
        return None
    value = container[key]
    if not isinstance(value, str):
        problems.append(f"{key} must be a string")
        return None
    if not value.strip():
        problems.append(f"{key} must not be empty")
        return None
    if "\x00" in value:
        problems.append(f"{key} must not contain NUL")
        return None
    return value


def _validate_string_list(value: Any, key: str, problems: list[str]) -> None:
    if not isinstance(value, list):
        problems.append(f"{key} must be a list of strings")
        return
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip() or "\x00" in item:
            problems.append(f"{key}[{index}] must be a non-empty string")


def _validate_integer(
    descriptor: dict[str, Any],
    key: str,
    minimum: int,
    maximum: int,
    problems: list[str],
) -> None:
    value = descriptor.get(key)
    if value is None:
        return
    if type(value) is not int:
        problems.append(f"{key} must be an integer")
        return
    if value < minimum or value > maximum:
        problems.append(f"{key} must be between {minimum} and {maximum}")


ALLOWED_TOP_LEVEL_FIELDS = {
    "version",
    "invocation",
    "childThread",
    "taskFile",
    "workflowId",
    "taskId",
    "role",
    "sessionKey",
    "scope",
    "tests",
    "dependsOn",
    "review",
    "session",
    "projectWorkingDirectory",
    "artifactRoot",
    "outputPath",
    "model",
    "name",
    "namePrefix",
    "maxBudgetUsd",
    "workerEffort",
    "sessionLeaseTimeoutSeconds",
    "sessionLeaseWaitSeconds",
    "resetPrimarySession",
    "resetParallelPool",
    "lockTimeoutSeconds",
    "lockPollMilliseconds",
    "maxRetryCount",
    "executionTimeoutSeconds",
    "silentTimeoutSeconds",
    "heartbeatSeconds",
    "trustedLocalFallback",
    "bypassPermissions",
    "dryRun",
}


def validate_descriptor(descriptor: dict[str, Any]) -> None:
    problems: list[str] = []
    if descriptor.get("version") != LAUNCH_SCHEMA_VERSION:
        problems.append(f"version must be {LAUNCH_SCHEMA_VERSION}")
    if descriptor.get("invocation") != ALLOWED_INVOCATION:
        problems.append(f"invocation must be {ALLOWED_INVOCATION}")

    unknown = set(descriptor) - ALLOWED_TOP_LEVEL_FIELDS
    if unknown:
        problems.append(f"unknown top-level fields: {sorted(unknown)}")

    child_thread = descriptor.get("childThread")
    if not isinstance(child_thread, dict):
        problems.append("childThread must be an object")
    else:
        unknown_child = set(child_thread) - {"threadId"}
        if unknown_child:
            problems.append(f"unknown childThread fields: {sorted(unknown_child)}")
        _require_string(child_thread, "threadId", problems)

    for key in (
        "taskFile",
        "workflowId",
        "taskId",
        "sessionKey",
        "projectWorkingDirectory",
    ):
        _require_string(descriptor, key, problems)

    role = descriptor.get("role")
    if role not in ALLOWED_ROLES:
        problems.append(f"role must be one of {sorted(ALLOWED_ROLES)}")

    for key in ("scope", "tests", "dependsOn"):
        if key in descriptor:
            _validate_string_list(descriptor[key], key, problems)

    review = descriptor.get("review")
    if review is not None:
        if not isinstance(review, dict):
            problems.append("review must be an object")
        else:
            unknown_review = set(review) - {
                "reviewForTaskId",
                "reviewForRunId",
                "reviewKind",
            }
            if unknown_review:
                problems.append(f"unknown review fields: {sorted(unknown_review)}")
            for key in ("reviewForTaskId", "reviewForRunId", "reviewKind"):
                _require_string(review, key, problems)
            if review.get("reviewKind") not in ALLOWED_REVIEW_KINDS:
                problems.append(
                    f"review.reviewKind must be one of {sorted(ALLOWED_REVIEW_KINDS)}"
                )
        if role != "reviewer":
            problems.append("review block is only allowed for role=reviewer")
    elif role == "reviewer":
        problems.append("review block is required for role=reviewer")

    session = descriptor.get("session")
    if session is not None:
        if not isinstance(session, dict):
            problems.append("session must be an object")
        else:
            unknown_session = set(session) - {"sessionMode", "allowParallel"}
            if unknown_session:
                problems.append(f"unknown session fields: {sorted(unknown_session)}")
            mode = session.get("sessionMode")
            if mode is not None and mode not in ALLOWED_SESSION_MODES:
                problems.append(
                    f"session.sessionMode must be one of {sorted(ALLOWED_SESSION_MODES)}"
                )
            allow_parallel = session.get("allowParallel")
            if allow_parallel is not None and type(allow_parallel) is not bool:
                problems.append("session.allowParallel must be boolean")
            if allow_parallel is True and not descriptor.get("scope"):
                problems.append("scope is required when session.allowParallel is true")

    for key in ("artifactRoot", "outputPath", "model", "name", "namePrefix"):
        if key in descriptor:
            _require_string(descriptor, key, problems)

    for key in ("artifactRoot", "outputPath"):
        value = descriptor.get(key)
        if isinstance(value, str) and not Path(value).expanduser().is_absolute():
            problems.append(f"{key} must be an absolute path")

    if descriptor.get("workerEffort") is not None and descriptor["workerEffort"] not in ("low", "medium", "high", "max"):
        problems.append("workerEffort must be low, medium, high or max")
    budget = descriptor.get("maxBudgetUsd")
    if budget is not None and (
        isinstance(budget, bool) or not isinstance(budget, (str, int, float))
    ):
        problems.append("maxBudgetUsd must be a string or number")

    for key, minimum, maximum in (
        ("sessionLeaseTimeoutSeconds", 1, 86400),
        ("sessionLeaseWaitSeconds", 1, 86400),
        ("lockTimeoutSeconds", 1, 86400),
        ("lockPollMilliseconds", 1, 86400),
        ("maxRetryCount", 0, 100),
        ("executionTimeoutSeconds", 1, 86400),
        ("silentTimeoutSeconds", 1, 86400),
        ("heartbeatSeconds", 1, 3600),
    ):
        _validate_integer(descriptor, key, minimum, maximum, problems)

    for key in (
        "resetPrimarySession",
        "resetParallelPool",
        "trustedLocalFallback",
        "bypassPermissions",
        "dryRun",
    ):
        if key in descriptor and type(descriptor[key]) is not bool:
            problems.append(f"{key} must be boolean")

    if problems:
        raise LaunchError("; ".join(problems))


def check_descriptor_safety(descriptor_dir: Path) -> Path:
    directory = _absolute_without_resolving(descriptor_dir)
    _check_secure_directory(directory, "descriptor directory")
    descriptor_path = directory / "launch.json"
    _check_no_symlink_components(descriptor_path, "launch.json")
    _check_owned_mode(descriptor_path, "launch.json", kind="file")
    return descriptor_path


def read_launch_descriptor(cwd: Path | None = None) -> dict[str, Any]:
    descriptor_path = check_descriptor_safety(cwd or Path.cwd())
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor_fd = os.open(str(descriptor_path), flags)
    except OSError as exc:
        raise LaunchError(f"launch.json cannot be opened safely: {exc}") from exc

    try:
        opened = os.fstat(descriptor_fd)
        current = _lstat(descriptor_path, "launch.json")
        if not stat.S_ISREG(opened.st_mode):
            raise LaunchError("launch.json is not a regular file")
        if opened.st_uid != os.getuid():
            raise LaunchError("launch.json is not owned by the current user")
        if stat.S_IMODE(opened.st_mode) & (stat.S_IWGRP | stat.S_IWOTH):
            raise LaunchError("launch.json is group- or world-writable")
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise LaunchError("launch.json changed while it was being opened")
        with os.fdopen(descriptor_fd, "r", encoding="utf-8") as handle:
            descriptor_fd = -1
            try:
                parsed = json.load(handle)
            except json.JSONDecodeError as exc:
                raise LaunchError(f"launch.json is not valid JSON: {exc}") from exc
    finally:
        if descriptor_fd >= 0:
            os.close(descriptor_fd)

    if not isinstance(parsed, dict):
        raise LaunchError("launch.json must be a JSON object")
    plan_path = descriptor_path.parent / "plan.json"
    if plan_path.exists():
        from .routing import verified_plan
        from .host_evidence import verify_active_child
        plan, _ = verified_plan(plan_path)
        if plan.get("backend") == "claude-process":
            from .process_run import validate_process_launch
            validate_process_launch(descriptor_path.parent)
            return parsed
        if plan.get("backend") != "claude-code" or parsed != plan.get("launchTemplate"):
            raise LaunchError("Prepared launch descriptor differs from its pinned template")
        actual = os.environ.get("CODEX_THREAD_ID", "")
        verify_active_child(actual, plan["projectRoot"], plan["model"], plan_path)
        # Binding is in memory: keep the original prepared descriptor immutable.
        parsed["childThread"] = {"threadId": actual}
    return parsed


def check_paths(descriptor: dict[str, Any], descriptor_dir: Path | None = None) -> None:
    del descriptor_dir
    project = Path(descriptor["projectWorkingDirectory"]).expanduser()
    if not project.is_absolute():
        raise LaunchError(f"projectWorkingDirectory must be absolute: {project}")
    project = _absolute_without_resolving(project)
    _check_secure_directory(project, "projectWorkingDirectory")
    if not os.access(project, os.W_OK):
        raise LaunchError(f"projectWorkingDirectory is not writable: {project}")

    task_value = descriptor["taskFile"]
    if task_value != task_value.strip():
        raise LaunchError("taskFile must not have leading or trailing whitespace")
    task_relative = Path(task_value)
    if task_relative.is_absolute():
        raise LaunchError(f"taskFile must be relative: {task_relative}")
    if ".." in task_relative.parts:
        raise LaunchError(f"taskFile must not contain ..: {task_relative}")

    task_path = project / task_relative
    _check_no_symlink_components(task_path, "taskFile")
    _check_owned_mode(task_path, "taskFile", kind="file")
    try:
        resolved_project = project.resolve(strict=True)
        resolved_task = task_path.resolve(strict=True)
        resolved_task.relative_to(resolved_project)
    except (OSError, ValueError) as exc:
        raise LaunchError(
            f"taskFile must resolve inside projectWorkingDirectory: {task_path}"
        ) from exc
    if not os.access(task_path, os.R_OK):
        raise LaunchError(f"taskFile is not readable: {task_path}")


def check_thread_binding(descriptor: dict[str, Any]) -> None:
    expected = descriptor["childThread"]["threadId"]
    actual = os.environ.get("CODEX_THREAD_ID", "")
    if descriptor.get("trustedLocalFallback") is True:
        return
    if not actual:
        raise LaunchError("CODEX_THREAD_ID is not set")
    if expected != actual:
        raise LaunchError(
            f"childThread.threadId mismatch: descriptor={expected} env={actual}"
        )


def claim_descriptor(descriptor_dir: Path) -> None:
    directory = _absolute_without_resolving(descriptor_dir)
    plan_path = directory / "plan.json"
    if plan_path.exists():
        from .routing import verified_plan
        from .workflow import workflow_lock_path
        from .locks import acquire_file_lock
        plan, _ = verified_plan(plan_path)
        lock = acquire_file_lock(workflow_lock_path(plan["artifactRoot"], plan["workflowId"]), 30, .05,
                                 lambda: "Prepared launcher claim is locked")
        try:
            verified_plan(plan_path)
            _claim_descriptor(directory)
        finally:
            lock.release()
        return
    _claim_descriptor(directory)


def _claim_descriptor(directory: Path) -> None:
    claim_path = directory / "claimed"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        claim_fd = os.open(str(claim_path), flags, 0o600)
    except FileExistsError as exc:
        raise LaunchError("descriptor has already been claimed") from exc
    except OSError as exc:
        raise LaunchError(f"failed to claim descriptor: {exc}") from exc
    with os.fdopen(claim_fd, "w", encoding="utf-8") as handle:
        handle.write(f"{os.getpid()}\n")
        handle.flush()
        os.fsync(handle.fileno())


def build_delegate_args(descriptor: dict[str, Any]) -> list[str]:
    arguments = [
        "delegate",
        "-TaskFile",
        descriptor["taskFile"],
        "-WorkflowId",
        descriptor["workflowId"],
        "-TaskId",
        descriptor["taskId"],
        "-Role",
        descriptor["role"],
        "-SessionKey",
        descriptor["sessionKey"],
    ]

    for key, flag in (
        ("scope", "-Scope"),
        ("tests", "-Tests"),
        ("dependsOn", "-DependsOn"),
    ):
        for value in descriptor.get(key, []):
            arguments.extend((flag, value))

    review = descriptor.get("review")
    if review:
        arguments.extend(
            (
                "-ReviewForTaskId",
                review["reviewForTaskId"],
                "-ReviewForRunId",
                review["reviewForRunId"],
                "-ReviewKind",
                review["reviewKind"],
            )
        )

    session = descriptor.get("session")
    if session:
        if session.get("sessionMode"):
            arguments.extend(("-SessionMode", session["sessionMode"]))
        if session.get("allowParallel") is True:
            arguments.append("-AllowParallel")

    for key, flag in (
        ("artifactRoot", "-ArtifactRoot"),
        ("outputPath", "-OutputPath"),
        ("model", "-Model"),
        ("workerEffort", "-WorkerEffort"),
        ("name", "-Name"),
        ("namePrefix", "-NamePrefix"),
        ("maxBudgetUsd", "-MaxBudgetUsd"),
        ("sessionLeaseTimeoutSeconds", "-SessionLeaseTimeoutSeconds"),
        ("sessionLeaseWaitSeconds", "-SessionLeaseWaitSeconds"),
        ("lockTimeoutSeconds", "-LockTimeoutSeconds"),
        ("lockPollMilliseconds", "-LockPollMilliseconds"),
        ("maxRetryCount", "-MaxRetryCount"),
        ("executionTimeoutSeconds", "-ExecutionTimeoutSeconds"),
        ("silentTimeoutSeconds", "-SilentTimeoutSeconds"),
        ("heartbeatSeconds", "-HeartbeatSeconds"),
    ):
        if key in descriptor:
            arguments.extend((flag, str(descriptor[key])))

    for key, flag in (
        ("resetPrimarySession", "-ResetPrimarySession"),
        ("resetParallelPool", "-ResetParallelPool"),
        ("trustedLocalFallback", "-TrustedLocalFallback"),
        ("bypassPermissions", "-BypassPermissions"),
        ("dryRun", "-DryRun"),
    ):
        if descriptor.get(key) is True:
            arguments.append(flag)
    return arguments


def run_delegate(arguments: list[str], project_cwd: Path) -> int:
    from .cli import main as runtime_main

    original_cwd = Path.cwd()
    try:
        os.chdir(project_cwd)
        return runtime_main(arguments)
    finally:
        os.chdir(original_cwd)


def main(argv: list[str] | None = None) -> int:
    selected_argv = sys.argv[1:] if argv is None else argv
    if selected_argv:
        print("codex-with-cc-launch: takes no command-line arguments", file=sys.stderr)
        return 2

    descriptor_dir = _absolute_without_resolving(Path.cwd())
    descriptor = read_launch_descriptor(descriptor_dir)
    if descriptor.get("invocation") == "codex_with_cc_process":
        from .process_run import run_process
        return run_process(descriptor_dir)
    validate_descriptor(descriptor)
    check_thread_binding(descriptor)
    check_paths(descriptor)
    claim_descriptor(descriptor_dir)

    os.environ[CHILD_MARKER_NAME] = CHILD_MARKER_VALUE
    plan_path = descriptor_dir / "plan.json"
    if not plan_path.is_file():
        return run_delegate(build_delegate_args(descriptor), Path(descriptor["projectWorkingDirectory"]))

    # The claimed prepared descriptor is unique. Keep complete diagnostics on
    # disk and deliver a bounded machine view, including nonzero exit outcomes.
    from contextlib import redirect_stdout, redirect_stderr
    from .packets import run_packet
    from .io_utils import load_json
    from .routing import verified_plan
    from .workflow import workflow_path
    plan, _ = verified_plan(plan_path)
    log_path = descriptor_dir / "carrier-output.log"
    execution_error = None
    with log_path.open("x", encoding="utf-8") as log, redirect_stdout(log), redirect_stderr(log):
        try:
            code = run_delegate(build_delegate_args(descriptor), Path(descriptor["projectWorkingDirectory"]))
        except Exception as exc:
            import traceback
            traceback.print_exc()
            code = 1
            execution_error = str(exc)[:500]
    result = {"exitCode": code, "runId": None, "logPath": str(log_path),
              "advisoryOnly": True, "deliveryStatus": "complete"}
    if execution_error is not None:
        result["executionError"] = execution_error
    try:
        root = Path(plan["artifactRoot"])
        state = load_json(workflow_path(root, plan["workflowId"]))
        rid = state["preparedTasks"][plan["planId"]].get("runId")
        result["runId"] = rid
        if rid:
            result["packet"] = run_packet(root, state, rid)
    except Exception as exc:
        # Preserve the actual execution exit code even if the delivery view fails.
        import traceback
        with log_path.open("a", encoding="utf-8") as log:
            traceback.print_exc(file=log)
        result["deliveryStatus"] = "failed"
        result["packetError"] = str(exc)[:500]
    print(json.dumps(result, ensure_ascii=False))
    return code if code else (1 if result["deliveryStatus"] == "failed" else 0)
