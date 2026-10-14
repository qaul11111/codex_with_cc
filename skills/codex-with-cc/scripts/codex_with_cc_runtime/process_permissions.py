"""Exact task-local Claude permissions. This is an authorization guard, not an OS sandbox."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
from pathlib import Path

from .common import DelegateError
from .io_utils import load_json
from .lifecycle import digest


def provider_snapshot(project: Path) -> dict:
    # Never persist credentials or raw settings. Pin current routing and permission
    # sources without replacing the user's provider or mutating global settings.
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    paths = [home / "settings.json", project / ".claude/settings.json", project / ".claude/settings.local.json"]
    env = {k: v for k, v in os.environ.items() if k.startswith(("ANTHROPIC_", "CLAUDE_CODE_USE_")) or k == "CLAUDE_CONFIG_DIR"}
    return {"settings": [{"path": str(p), "sha256": digest(p) if p.is_file() else None} for p in paths],
            "environmentSha256": hashlib.sha256(json.dumps(env, sort_keys=True).encode()).hexdigest(),
            "policy": "preserve-current-provider"}


def allowed_commands(path: str | None, project: Path) -> list[dict]:
    if path is None:
        return []
    value = load_json(Path(path))
    if set(value) != {"schemaVersion", "commands"} or value["schemaVersion"] != 1 or not isinstance(value["commands"], list):
        raise DelegateError("AllowedCommandsFile requires schemaVersion 1 and commands list")
    result = []
    for entry in value["commands"]:
        if not isinstance(entry, dict) or set(entry) - {"argv", "pinnedFiles"}:
            raise DelegateError("Command authorization accepts only argv and pinnedFiles")
        argv = entry.get("argv")
        if not isinstance(argv, list) or not argv or any(not isinstance(a, str) or not a or not re.fullmatch(r"[A-Za-z0-9_./:=+@%,-]+", a) for a in argv):
            raise DelegateError("Authorized argv must be literal simple arguments; shell metacharacters, whitespace and globs are forbidden")
        executable = Path(argv[0]).name
        if executable in {"sh", "bash", "zsh", "fish", "env", "sudo", "eval", "exec", "xargs"}:
            raise DelegateError("Shell and generic command wrappers cannot be authorized")
        pins = entry.get("pinnedFiles", [])
        if not isinstance(pins, list) or any(not isinstance(p, str) for p in pins):
            raise DelegateError("pinnedFiles must be a list of project-relative paths")
        normalized = []
        for name in pins:
            target = project / name
            if Path(name).is_absolute() or ".." in Path(name).parts or target.is_symlink() or not target.resolve().is_relative_to(project.resolve()) or not target.is_file():
                raise DelegateError("Pinned scripts must be regular files inside the project")
            normalized.append({"path": str(target.resolve()), "sha256": digest(target)})
        # Interpreters require a pinned file, never -c/-e/stdin/module execution.
        if re.fullmatch(r"python[0-9.]*|node|ruby|perl|php|pwsh", executable):
            if len(argv) < 2 or argv[1].startswith("-") or not any(str((project / argv[1]).resolve()) == p["path"] for p in normalized):
                raise DelegateError("Interpreter commands require a pinned script as the first argument; inline code is forbidden")
        if len(argv) == 1 and executable in {"python", "python3", "node", "ruby", "perl"}:
            raise DelegateError("A broad interpreter allowance is forbidden")
        command = shlex.join(argv)
        if any(r["command"] == command for r in result):
            raise DelegateError("Duplicate command authorization")
        result.append({"argv": argv, "command": command, "pinnedFiles": normalized})
    return result


def verify_command_pins(plan: dict) -> None:
    for entry in plan["allowedCommands"]:
        if shlex.join(entry["argv"]) != entry["command"]:
            raise DelegateError("Canonical command authorization changed")
        for pin in entry["pinnedFiles"]:
            p = Path(pin["path"])
            if not p.is_file() or p.is_symlink() or digest(p) != pin["sha256"]:
                raise DelegateError("Authorized command script content changed")


def authorize_tool(plan: dict, event: dict) -> tuple[bool, str]:
    name, data = event.get("tool_name"), event.get("tool_input") or {}
    if event.get("cwd") and Path(event["cwd"]).resolve() != Path(plan["projectRoot"]).resolve():
        return False, "Tool working directory differs from the prepared project"
    if name == "Bash":
        verify_command_pins(plan)
        if data.get("run_in_background"):
            return False, "Background commands are outside task authorization"
        return (data.get("command") in [c["command"] for c in plan["allowedCommands"]], "Only the exact prepared commands are authorized")
    if name in ("Read", "Glob", "Grep"):
        return True, "Read-only exploration"
    if name == "StructuredOutput":
        return True, "Internal JSON-schema report delivery has no command or file side effects"
    if name in ("Edit", "Write") and plan["role"] == "implementer":
        value = data.get("file_path")
        if not isinstance(value, str):
            return False, "Missing file path"
        project = Path(plan["projectRoot"]).resolve()
        target = (project / value).resolve()
        authorized = any(target.is_relative_to((project / scope).resolve()) for scope in plan["scope"])
        protected = target.is_relative_to(Path(plan["artifactRoot"]).resolve()) or any(target == Path(pin["path"]) for c in plan["allowedCommands"] for pin in c["pinnedFiles"])
        return authorized and not protected, "Writes require task scope and must not alter artifacts or pinned command scripts"
    return False, "Tool is outside this prepared task's authority"


def permission_hook(plan_path: Path, event: dict) -> dict:
    from .routing import verified_plan
    try:
        plan, _ = verified_plan(plan_path)
        if plan.get("backend") != "claude-process":
            raise DelegateError("Permission guard requires claude-process")
        allowed, reason = authorize_tool(plan, event)
    except (DelegateError, OSError, ValueError, KeyError) as exc:
        allowed, reason = False, str(exc)
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow" if allowed else "deny", "permissionDecisionReason": reason}}
