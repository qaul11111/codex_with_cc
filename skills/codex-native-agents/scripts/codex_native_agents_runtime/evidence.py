"""Local host and source evidence. These checks do not authenticate a hostile local user."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
from pathlib import Path

from .common import ContractError


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def capabilities(path: Path) -> dict:
    data = json.loads(path.read_text())
    return validate_capabilities(data)


def validate_capabilities(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ContractError("Host capabilities must be a JSON object")
    if data.get("source") != "active-tool-catalog":
        raise ContractError("Capabilities must come from the active-tool-catalog")
    tools = data.get("tools")
    if not isinstance(tools, list) or any(
        not isinstance(name, str) or not name.strip() for name in tools
    ):
        raise ContractError("Host tools must be a list of non-empty tool names")
    names = {name.replace("__", ".").split(".")[-1] for name in tools}
    # Discovery is optional: workflow state and original transcripts track owned agents.
    if "spawn_agent" not in names or not names.intersection({"wait_agent", "wait"}):
        raise ContractError("Host needs native spawn_agent and wait_agent/wait tools")
    if data.get("forkParameter") not in {"fork_turns", "fork_context"}:
        raise ContractError("Host must declare its actual forkParameter")
    models = data.get("models")
    if not isinstance(models, dict) or any(
        not isinstance(model, str)
        or not model.strip()
        or not isinstance(efforts, list)
        or any(not isinstance(effort, str) or not effort.strip() for effort in efforts)
        or len(efforts) != len(set(efforts))
        for model, efforts in models.items()
    ):
        raise ContractError("Host models must map model names to unique effort-name lists")
    if (
        not isinstance(data.get("maxAgents"), int)
        or isinstance(data["maxAgents"], bool)
        or data["maxAgents"] < 1
    ):
        raise ContractError("maxAgents must be the available child concurrency limit")
    return {
        **data,
        "lifecycle": "strict-close" if "close_agent" in names else "terminal-evidence",
    }


def snapshot(project: str, artifact_root: str) -> dict:
    root, artifacts = Path(project).resolve(), Path(artifact_root).resolve()
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    files = {}
    for name in sorted(set(os.fsdecode(x) for x in result.stdout.split(b"\0") if x)):
        path = root / name
        if path == artifacts or artifacts in path.parents:
            continue
        if path.is_symlink():
            files[name] = {"symlink": os.readlink(path)}
        elif path.is_file():
            files[name] = {"hash": digest(path), "mode": path.stat().st_mode & 0o777}
        elif not path.exists():
            files[name] = None
        else:
            raise ContractError(
                "Source snapshot cannot cover directory/submodule: " + name
            )
    return files


def host_records(path: Path) -> list[dict]:
    sessions = (
        Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions"
    ).resolve()
    if not path.resolve().is_relative_to(sessions):
        raise ContractError(
            "Evidence must use an original CODEX_HOME/sessions transcript"
        )
    records = [
        json.loads(line) for line in path.read_text().splitlines() if line.strip()
    ]
    if not records or records[0].get("type") != "session_meta":
        raise ContractError("Original host session_meta is required")
    return records


def main_identity(project: str) -> dict:
    thread = os.environ.get("CODEX_THREAD_ID")
    sessions = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions"
    paths = list(sessions.rglob(f"*{thread}.jsonl")) if thread else []
    if len(paths) != 1:
        raise ContractError("Cannot locate original main-thread identity")
    meta = host_records(paths[0])[0]["payload"]
    source = meta.get("source")
    if (
        meta.get("id") != thread
        or Path(meta.get("cwd", "")).resolve() != Path(project).resolve()
        or (isinstance(source, dict) and source.get("subagent"))
        or meta.get("parent_thread_id")
        or meta.get("thread_source") == "subagent"
    ):
        raise ContractError(
            "Acceptance requires the original main thread in this project"
        )
    return {
        "threadId": thread,
        "metadataHash": fingerprint(meta),
        "path": str(paths[0].resolve()),
    }


def terminal(
    path: Path,
    agent: str,
    project: str,
    *,
    model: str | None = None,
    effort: str | None = None,
) -> dict:
    records = host_records(path)
    meta = records[0]["payload"]
    source = meta.get("source") or {}
    spawn = (
        ((source.get("subagent") or {}).get("thread_spawn") or {})
        if isinstance(source, dict)
        else {}
    )
    parent = spawn.get("parent_thread_id") or meta.get("parent_thread_id")
    if (
        not parent
        or agent not in {meta.get("id"), spawn.get("agent_path")}
        or Path(meta.get("cwd", "")).resolve() != Path(project).resolve()
    ):
        raise ContractError("Original child identity/project mismatch")
    start, event, final, contexts, turn_id, terminal_index = (
        None,
        None,
        "",
        [],
        None,
        None,
    )
    final_candidate = None
    for index, r in enumerate(records):
        p = r.get("payload") or {}
        if r.get("type") == "event_msg" and p.get("type") == "task_started":
            start, event, final, contexts, turn_id = r, None, "", [], p.get("turn_id")
            final_candidate = None
        elif r.get("type") == "turn_context" and start and event is None:
            contexts.append(
                (
                    p.get("model"),
                    p.get(
                        "effort",
                        p.get("reasoning_effort", p.get("model_reasoning_effort")),
                    ),
                )
            )
        elif (
            r.get("type") == "response_item"
            and p.get("type") == "message"
            and p.get("role") == "assistant"
            and start
            and event is None
        ):
            if (
                (p.get("channel") == "final" or p.get("phase") == "final_answer")
                and p.get("channel") in {None, "final"}
                and p.get("phase") in {None, "final_answer"}
            ):
                final_candidate = "\n".join(
                    x.get("text", "")
                    for x in p.get("content", [])
                    if x.get("type") in {"text", "output_text"}
                )
                message_turn = (
                    p.get("internal_chat_message_metadata_passthrough") or {}
                ).get("turn_id", turn_id)
                final = final_candidate if message_turn == turn_id else ""
        elif r.get("type") == "event_msg" and p.get("type") in {
            "task_complete",
            "turn_aborted",
        }:
            if start and event is None and turn_id and p.get("turn_id") == turn_id:
                event = r
                terminal_index = index
                if p.get("type") == "task_complete" and "last_agent_message" in p:
                    # Relays can retain an upstream turn ID in message metadata.
                    # Bind the final to this host turn only when its completion
                    # receipt exactly repeats the final observed inside the turn.
                    final = (
                        final_candidate
                        if final_candidate is not None
                        and p["last_agent_message"] == final_candidate
                        else ""
                    )
    if (
        not start
        or not event
        or not event.get("timestamp")
        or not start.get("timestamp")
    ):
        raise ContractError("Original child has no terminal host turn")
    aborted = event["payload"]["type"] == "turn_aborted"
    if (
        model
        and not aborted
        and (not contexts or any(m != model or e != effort for m, e in contexts))
    ):
        raise ContractError(
            "Actual model/reasoning effort differs from the prepared route"
        )
    return {
        "path": str(path.resolve()),
        "sha256": fingerprint(records[: terminal_index + 1]),
        "threadId": meta["id"],
        "agentId": agent,
        "parentThreadId": parent,
        "turnId": turn_id,
        "startedAt": start["timestamp"],
        "terminalAt": event["timestamp"],
        "event": event["payload"]["type"],
        "model": contexts[-1][0] if contexts else None,
        "effort": contexts[-1][1] if contexts else None,
        "final": final,
    }


def recheck_terminal(record: dict, project: str) -> None:
    actual = terminal(Path(record["path"]), record["agentId"], project)
    if actual != record:
        raise ContractError("Original terminal evidence changed; use a fresh attempt")


def close_confirmation(path: Path, terminal_record: dict, project: str) -> dict:
    records = host_records(path)
    meta = records[0]["payload"]
    if (
        meta.get("id") != terminal_record["parentThreadId"]
        or Path(meta.get("cwd", "")).resolve() != Path(project).resolve()
    ):
        raise ContractError("Close evidence requires the original parent transcript")
    calls = {}
    for r in records:
        p = r.get("payload") or {}
        if (
            p.get("type") in {"function_call", "custom_tool_call"}
            and str(p.get("name", "")).replace("__", ".").split(".")[-1]
            == "close_agent"
        ):
            try:
                args = json.loads(p.get("arguments", p.get("input", "{}")))
            except (ValueError, TypeError):
                continue
            if args.get("agent_id", args.get("id", args.get("target"))) in {
                terminal_record["agentId"],
                terminal_record["threadId"],
            }:
                calls[p.get("call_id")] = r
        if (
            p.get("type") in {"function_call_output", "custom_tool_call_output"}
            and p.get("call_id") in calls
        ):
            try:
                output = json.loads(p.get("output", "{}"))
            except (ValueError, TypeError):
                continue
            if (
                isinstance(output, dict)
                and output
                and not output.get("error")
                and not output.get("isError")
            ):
                if str(r.get("timestamp", "")) < terminal_record["terminalAt"]:
                    continue
                return {
                    "path": str(path.resolve()),
                    "records": [calls[p["call_id"]], r],
                }
    raise ContractError("No successful original close_agent result for this attempt")


def runs_snapshot(workflow: dict) -> dict:
    return {tid: task["latestRunId"] for tid, task in workflow["tasks"].items()}


def run_checks(
    workflow: dict, checks_file: Path, *, expected_source: dict | None = None,
    check_lock_fd: int | None = None,
) -> dict:
    policy = workflow["policy"]
    before = snapshot(policy["projectRoot"], policy["artifactRoot"])
    if expected_source is not None and before != expected_source:
        raise ContractError("Check source changed before execution; rerun current checks")
    checks = json.loads(checks_file.read_text()).get("checks")
    if not isinstance(checks, list) or not checks:
        raise ContractError("Checks must contain explicit argv commands")
    outputs = []
    for check in checks:
        argv = check.get("argv")
        timeout = check.get("timeoutSeconds", 300)
        cwd = (Path(policy["projectRoot"]) / check.get("cwd", ".")).resolve()
        if (
            not isinstance(argv, list)
            or not argv
            or any(not isinstance(x, str) or not x for x in argv)
            or not cwd.is_relative_to(Path(policy["projectRoot"]))
        ):
            raise ContractError("Invalid check argv/cwd")
        if (
            not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or timeout <= 0
            or timeout > 1800
        ):
            raise ContractError("Check timeout must be between 0 and 1800 seconds")
        child = subprocess.Popen(
            argv,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
            # Keep the execution lock alive if the CLI is SIGKILLed. Commands
            # must stay in the foreground and preserve inherited descriptors.
            pass_fds=(check_lock_fd,) if os.name != "nt" and check_lock_fd is not None else (),
        )
        try:
            output, _ = child.communicate(timeout=timeout)
        except BaseException as error:
            if os.name != "nt":
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                child.kill()
            child.communicate()
            if isinstance(error, subprocess.TimeoutExpired):
                raise ContractError("Verification command timed out") from error
            raise
        if child.returncode:
            raise ContractError(
                f"Verification failed ({child.returncode}): {argv}\n"
                + output.decode(errors="replace")[-4000:]
            )
        outputs.append(
            {
                "argv": argv,
                "cwd": str(cwd),
                "exitCode": child.returncode,
                "output": output.decode(errors="replace"),
            }
        )
    if snapshot(policy["projectRoot"], policy["artifactRoot"]) != before:
        raise ContractError("Checks changed source inputs; inspect changes and rerun")
    return {"source": before, "runs": runs_snapshot(workflow), "checks": outputs}
