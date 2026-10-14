"""Run explicit argv checks and bind main-thread acceptance to their code snapshot."""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import uuid
from pathlib import Path

from .common import DelegateError, now_iso, same_path
from .execution_policy import profile, require_main_thread, main_review_current
from .io_utils import load_json, write_json
from .lifecycle import digest
from .locks import acquire_file_lock


def tree_snapshot(project: Path, artifact_root: Path, scopes: list[str] | None = None) -> str:
    """Include tracked modifications/deletions and untracked nonignored inputs."""
    result = subprocess.run(["git", "-C", str(project), "ls-files", "-co", "--exclude-standard", "-z"], capture_output=True)
    if result.returncode:
        raise DelegateError("Evidence checks require a Git project to enumerate the tested inputs")
    entries = []
    for name in sorted(set(result.stdout.decode().split("\0")) - {""}):
        if scopes is not None and not any(Path(name).is_relative_to(Path(scope)) for scope in scopes):
            continue
        p = project / name
        if scopes is not None and (p.is_symlink() or any(parent.is_symlink() for parent in p.parents if parent != project and parent.is_relative_to(project))):
            raise DelegateError("Scoped checks cannot certify symlink inputs; use full-project checks")
        if p.is_relative_to(artifact_root) or name.startswith(".codex/codex_with_cc/"):
            continue
        if p.is_symlink():
            value = "link:" + os.readlink(p)
        elif p.is_file():
            value = digest(p) + ":" + oct(p.stat().st_mode & 0o777)
        else:
            value = "missing"
        entries.append([name, value])
    return hashlib.sha256(json.dumps(entries, ensure_ascii=False).encode()).hexdigest()


def snapshot_policy(workflow: dict, extra_scopes: list[str], reason: str | None) -> dict | None:
    if not extra_scopes:
        return None
    if not reason or not reason.strip():
        raise DelegateError("Scoped checks require ScopeReason explaining dependency coverage")
    from .adaptive import normalize_scopes
    from .routing import verified_plan
    project = Path(workflow["executionPolicy"]["projectRoot"])
    extra = normalize_scopes(project, extra_scopes)
    inputs = list(extra); pins = {}
    if not workflow.get("tasks"):
        raise DelegateError("Scoped checks need recorded task inputs")
    for tid, task in workflow["tasks"].items():
        config = load_json(Path(workflow["runs"][task["latestRunId"]]["configPath"]))
        entry = workflow.get("preparedTasks", {}).get(config.get("preparedPlanId"))
        if not entry:
            raise DelegateError("Scoped checks require prepared plans; use full-project checks")
        plan, _ = verified_plan(Path(entry["path"]))
        if not plan.get("inputsComplete"):
            raise DelegateError("Task input dependencies are not declared complete; use full-project checks")
        inputs.extend(plan["scope"] + plan.get("readScope", []))
        pins[tid] = entry["sha256"]
    return {"schemaVersion": 1, "scopes": normalize_scopes(project, inputs), "extraScopes": extra,
            "reason": reason, "planHashes": pins}


def run_checks(ns) -> int:
    from .artifacts import resolve_artifact_root
    from .workflow import workflow_path
    root = resolve_artifact_root(ns.artifact_root, workflow_id=ns.workflow_id)
    w = load_json(workflow_path(root, ns.workflow_id))
    project = Path((w.get("executionPolicy") or {}).get("projectRoot") or "").resolve()
    if not w.get("executionPolicy"):
        raise DelegateError("Configure a new workflow before recording checks")
    checks = load_json(Path(ns.checks_file)).get("checks")
    if not isinstance(checks, list) or not checks:
        raise DelegateError("Checks file must contain a nonempty checks array")
    # Validate the entire batch before executing its first command.
    for check in checks:
        argv = check.get("argv") if isinstance(check, dict) else None
        if not isinstance(argv, list) or not argv or any(not isinstance(x, str) or not x or '\0' in x for x in argv):
            raise DelegateError("Each check requires a nonempty string argv array")
        cwd = (project / str(check.get("cwd") or ".")).resolve()
        timeout = check.get("timeoutSeconds", 300)
        if not cwd.is_relative_to(project) or not cwd.is_dir():
            raise DelegateError("Check cwd must stay inside the project")
        if type(timeout) is not int or not 1 <= timeout <= 3600:
            raise DelegateError("Check timeoutSeconds must be between 1 and 3600")
    selection = snapshot_policy(w, getattr(ns, "input_scope", []), getattr(ns, "scope_reason", None))
    selected_scopes = selection["scopes"] if selection else None
    before = tree_snapshot(project, root, selected_scopes)
    evidence_id = uuid.uuid4().hex
    folder = root / "checks" / evidence_id
    folder.mkdir(parents=True)
    results = []
    started = now_iso()
    for index, check in enumerate(checks):
        stdout, stderr = folder / f"{index}.stdout.log", folder / f"{index}.stderr.log"
        row = {"argv": check["argv"], "cwd": str((project / str(check.get("cwd") or ".")).resolve()), "startedAt": now_iso()}
        try:
            with stdout.open("wb") as out, stderr.open("wb") as err:
                from .process_cleanup import terminate_process_tree
                child = subprocess.Popen(check["argv"], cwd=row["cwd"], stdout=out, stderr=err,
                                         start_new_session=os.name == "posix")
                try:
                    row["exitCode"] = child.wait(timeout=check.get("timeoutSeconds", 300))
                finally:
                    if child.poll() is None:
                        terminate_process_tree(child)
                        child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            row["exitCode"] = 124
        except OSError as exc:
            row["exitCode"] = 127
            stderr.write_text(str(exc))
        row.update({"finishedAt": now_iso(), "stdout": str(stdout), "stderr": str(stderr),
                    "stdoutSha256": digest(stdout), "stderrSha256": digest(stderr)})
        results.append(row)
        if row["exitCode"] != 0:
            break
    after = tree_snapshot(project, root, selected_scopes)
    evidence = {"schemaVersion": 1, "workflowId": ns.workflow_id, "projectRoot": str(project),
                "startedAt": started, "finishedAt": now_iso(), "beforeTree": before, "afterTree": after,
                "checks": results, "allPassed": len(results) == len(checks) and all(r["exitCode"] == 0 for r in results) and before == after,
                "runs": {tid: task.get("latestRunId") for tid, task in w.get("tasks", {}).items()}}
    if selection:
        evidence["snapshotPolicy"] = selection
    path = folder / "evidence.json"
    write_json(path, evidence)
    print(path)
    return 0 if evidence["allPassed"] else 1


def verify_check_file(path: Path, root: Path, workflow: dict) -> dict:
    if not path.resolve().is_relative_to((root / "checks").resolve()):
        raise DelegateError("Check evidence must be inside this workflow artifact root")
    e = load_json(path)
    project = Path(workflow["executionPolicy"]["projectRoot"])
    if e.get("schemaVersion") != 1 or e.get("workflowId") != workflow["workflowId"] or not same_path(e.get("projectRoot", ""), project):
        raise DelegateError("Check evidence workflow/project mismatch")
    if not e.get("allPassed") or not e.get("checks") or e.get("beforeTree") != e.get("afterTree"):
        raise DelegateError("Check evidence is failed, empty or changed the tested inputs")
    expected = {tid: task.get("latestRunId") for tid, task in workflow.get("tasks", {}).items()}
    selection = e.get("snapshotPolicy")
    if selection is not None:
        if not isinstance(selection, dict) or not selection.get("extraScopes") or snapshot_policy(workflow, selection["extraScopes"], selection.get("reason")) != selection:
            raise DelegateError("Scoped evidence dependency declaration changed")
    if e.get("runs") != expected or e.get("afterTree") != tree_snapshot(project, root, selection["scopes"] if selection else None):
        raise DelegateError("Check evidence is stale after a run or source change")
    for row in e["checks"]:
        if type(row.get("exitCode")) is not int or row["exitCode"] != 0 or not row.get("argv"):
            raise DelegateError("A required check did not pass")
        for key in ("stdout", "stderr"):
            log = Path(row.get(key, ""))
            if not log.resolve().is_relative_to(path.parent.resolve()) or not log.is_file() or digest(log) != row.get(key + "Sha256"):
                raise DelegateError("Check log is missing or changed")
    declared = {test for t in workflow.get("tasks", {}).values() for test in t.get("verification", []) if test.strip()}
    commands = [row["argv"] for row in e["checks"]]
    for test in declared:
        try:
            argv = shlex.split(test)
        except ValueError as exc:
            raise DelegateError("Declared verification command is malformed") from exc
        if not any(command == argv or (len(command) == 3 and Path(command[0]).name in ("sh", "bash", "zsh") and command[1] == "-c" and command[2] == test) for command in commands):
            raise DelegateError(f"Executed checks do not cover declared verification: {test}")
    return e


def run_main_review(ns) -> int:
    from .artifacts import resolve_artifact_root, verify_artifacts, enforce_current_report_consistency
    from .workflow import workflow_path, workflow_lock_path, update_workflow_acceptance
    root = resolve_artifact_root(ns.artifact_root, workflow_id=ns.workflow_id)
    thread = require_main_thread()
    lock = acquire_file_lock(workflow_lock_path(root, ns.workflow_id), 30, .05, lambda: "Main review is locked")
    try:
        path = workflow_path(root, ns.workflow_id)
        w = load_json(path)
        if profile(w) != "standard":
            raise DelegateError("Main-thread acceptance is only available for explicitly configured standard workflows")
        if not w.get("tasks") or not w.get("runs"):
            raise DelegateError("Cannot review an empty workflow")
        if any(thread in (a.get("codexThreadId"), a.get("agentId")) for a in w.get("agentAttempts", {}).values()):
            raise DelegateError("A worker cannot approve its own workflow")
        from .host_evidence import verify_main_identity
        identity = verify_main_identity(thread, w["executionPolicy"]["projectRoot"])
        records = {rid: verify_artifacts(rid, str(root), recover_status=False, allow_interrupted=True) for rid in w["runs"]}
        enforce_current_report_consistency(w, records, require_all=True)
        from .review_decisions import reviewable, validate_decisions
        if any(not reviewable(t) for t in w["tasks"].values()):
            raise DelegateError("Main review requires completed DONE or DONE_WITH_CONCERNS tasks; blockers cannot be waived")
        decisions_file = getattr(ns, "decisions_file", None)
        decisions = validate_decisions(w, load_json(Path(decisions_file)) if decisions_file else {"decisions": []})
        from .execution_policy import verify_project
        verify_project(w, records)
        evidence = Path(ns.evidence_file).resolve()
        verify_check_file(evidence, root, w)
        note = Path(ns.review_file).read_text().strip()
        if not note or len(note) < 40:
            raise DelegateError("Review must explain scope compliance, quality findings and residual risks")
        review_path = root / "checks" / f"review-{uuid.uuid4().hex}.md"
        review_path.write_text(note)
        w["mainReview"] = {"decision": "accepted", "reviewerThreadId": thread, "identity": identity,
                           "recordedAt": now_iso(), "runs": {tid: t["latestRunId"] for tid, t in w["tasks"].items()},
                           "evidencePath": str(evidence), "evidenceSha256": digest(evidence),
                           "reviewPath": str(review_path), "reviewSha256": digest(review_path)}
        if decisions["decisions"]:
            decision_path = root / "checks" / f"decisions-{uuid.uuid4().hex}.json"
            write_json(decision_path, decisions)
            w["mainReview"]["concernDecisions"] = {"path": str(decision_path), "sha256": digest(decision_path)}
        update_workflow_acceptance(w)
        write_json(path, w)
    finally:
        lock.release()
    print("Main-thread review recorded; run verify-workflow after lifecycle settlement")
    return 0


def verify_main_review(root: Path, workflow: dict) -> None:
    if profile(workflow) != "standard":
        return
    if not main_review_current(workflow):
        raise DelegateError("Missing or stale main-thread review")
    r = workflow["mainReview"]
    from .host_evidence import verify_main_identity
    if verify_main_identity(r["reviewerThreadId"], workflow["executionPolicy"]["projectRoot"]) != r.get("identity"):
        raise DelegateError("Main-thread identity changed")
    for key in ("evidence", "review"):
        p = Path(r.get(key + "Path", ""))
        if not p.resolve().is_relative_to((root / "checks").resolve()) or not p.is_file() or digest(p) != r.get(key + "Sha256"):
            raise DelegateError("Main review evidence was changed")
    verify_check_file(Path(r["evidencePath"]), root, workflow)
    from .review_decisions import verify_decisions
    verify_decisions(root, workflow)
