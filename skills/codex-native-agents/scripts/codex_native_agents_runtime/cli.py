from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from .workflow import (
    WorkflowError,
    load_workflow,
    new_workflow,
    record_close,
    record_run,
    record_spawn,
    register_task,
    verify_workflow,
    workflow_lock,
    workflow_path,
    write_workflow,
)
from .task_contract import validate_task_file
from .routing import route_for_task
from . import evidence, planning


DEFAULT_ARTIFACT_ROOT = Path(".codex/codex_native_agents/workflows")


def _add_artifact_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--artifact-root", type=Path, default=argparse.SUPPRESS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record and verify native Codex agent workflows"
    )
    _add_artifact_root(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init")
    _add_artifact_root(init)
    init.add_argument("--workflow-id", required=True)
    init.add_argument("--profile", choices=("standard", "strict"), default="standard")
    init.add_argument("--project-root", type=Path, default=Path.cwd())
    init.add_argument("--host-capabilities", type=Path, required=True)
    init.add_argument("--main-scope", action="append", default=[])

    advise = subparsers.add_parser("advise")
    advise.add_argument(
        "--complexity",
        choices=("simple", "normal", "complex", "high-risk"),
        default="normal",
    )
    advise.add_argument("--independent", action="store_true")
    advise.add_argument("--coupled", action="store_true")
    advise.add_argument("--estimated-minutes", type=float, required=True)
    advise.add_argument("--overhead-minutes", type=float, default=2)
    advise.add_argument("--multi-agent-mode", choices=("enabled", "explicit-only", "disabled", "unknown"), default="unknown")
    advise.add_argument("--delegation-request", choices=("none", "user", "agents", "skill"), default="none")
    advise.add_argument("--user-restriction", choices=("none", "no-agents", "serial"), default="none")
    advise.add_argument("--main-work-available", action="store_true")

    route = subparsers.add_parser(
        "route", help="Inspect a route without creating or dispatching a workflow"
    )
    route.add_argument("--role", required=True)
    route.add_argument("--complexity", default="normal")
    route.add_argument("--host-capabilities", type=Path, required=True)
    route.add_argument(
        "--model-profile", help="Explicit fixed profile; unavailable profiles return to main"
    )

    for command in (
        "ready",
        "prepare-spawn",
        "run-checks",
        "record-main-review",
        "verify-final-inputs",
    ):
        operation = subparsers.add_parser(command)
        _add_artifact_root(operation)
        operation.add_argument("--workflow-id", required=True)
        if command in {"prepare-spawn", "verify-final-inputs"}:
            operation.add_argument("--task-id", required=True)
        if command == "prepare-spawn":
            operation.add_argument("--escalate", action="store_true")
        if command == "run-checks":
            operation.add_argument("--checks-file", type=Path, required=True)
        if command == "record-main-review":
            operation.add_argument("--review-file", type=Path, required=True)

    validate = subparsers.add_parser("validate-task")
    validate.add_argument("--task-file", type=Path, required=True)
    validate.add_argument("--role", required=True)

    register = subparsers.add_parser("register-task")
    _add_artifact_root(register)
    register.add_argument("--workflow-id", required=True)
    register.add_argument("--task-id", required=True)
    register.add_argument("--role", required=True)
    register.add_argument("--task-file", type=Path, required=True)
    register.add_argument("--scope", action="append", required=True)
    register.add_argument("--writable", action="store_true")
    register.add_argument("--parallel", action="store_true")
    register.add_argument(
        "--model-profile",
        help="User-selected fixed profile; no automatic replacement or escalation",
    )
    register.add_argument("--complexity", default="normal")
    register.add_argument("--review-for-task-id")
    register.add_argument("--review-kind")
    register.add_argument("--depends-on", action="append", default=[])

    record = subparsers.add_parser("record-run")
    _add_artifact_root(record)
    record.add_argument("--workflow-id", required=True)
    record.add_argument("--task-id", required=True)
    record.add_argument("--agent-id", required=True)
    record.add_argument("--report-file", type=Path, required=True)
    record.add_argument("--run-id")
    record.add_argument("--started-at")
    record.add_argument("--transcript-path", type=Path, required=True)

    spawn = subparsers.add_parser("record-spawn")
    _add_artifact_root(spawn)
    spawn.add_argument("--workflow-id", required=True)
    spawn.add_argument("--task-id", required=True)
    spawn.add_argument("--agent-id", required=True)
    spawn.add_argument("--actual-model")
    spawn.add_argument("--inherit-parent", action="store_true")
    spawn.add_argument("--fallback-reason")

    close = subparsers.add_parser("record-close")
    _add_artifact_root(close)
    close.add_argument("--workflow-id", required=True)
    close.add_argument("--task-id", required=True)
    close.add_argument("--agent-id", required=True)
    close.add_argument("--status", required=True)
    close.add_argument("--transcript-path", type=Path, required=True)
    close.add_argument("--close-transcript", type=Path)

    verify = subparsers.add_parser("verify")
    _add_artifact_root(verify)
    verify.add_argument("--workflow-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    artifact_root = getattr(args, "artifact_root", DEFAULT_ARTIFACT_ROOT)
    try:
        if args.command == "route":
            host = evidence.capabilities(args.host_capabilities)
            route = route_for_task(
                args.role,
                args.complexity,
                capabilities=host["models"],
                model_profile=args.model_profile,
            )
            print(json.dumps(asdict(route), indent=2))
            return 0
        if args.command == "advise":
            print(
                json.dumps(
                    planning.advise(
                        complexity=args.complexity,
                        independent=args.independent,
                        coupled=args.coupled,
                        estimated_minutes=args.estimated_minutes,
                        overhead_minutes=args.overhead_minutes,
                        multi_agent_mode=args.multi_agent_mode,
                        delegation_request=args.delegation_request,
                        user_restriction=args.user_restriction,
                        main_work_available=args.main_work_available,
                    ),
                    indent=2,
                )
            )
            return 0
        if args.command == "validate-task":
            validate_task_file(args.task_file, args.role)
            print(args.task_file)
            return 0
        with workflow_lock(artifact_root, args.workflow_id):
            if args.command == "init":
                if workflow_path(artifact_root, args.workflow_id).exists():
                    raise WorkflowError(f"Workflow already exists: {args.workflow_id}")
                path = write_workflow(
                    artifact_root,
                    new_workflow(
                        args.workflow_id,
                        project_root=args.project_root,
                        artifact_root=artifact_root,
                        profile=args.profile,
                        host=evidence.capabilities(args.host_capabilities),
                        main_scopes=args.main_scope,
                    ),
                )
            else:
                workflow = load_workflow(artifact_root, args.workflow_id)
                if (
                    args.command
                    in {"prepare-spawn", "run-checks", "record-main-review"}
                    and workflow["status"] == "accepted"
                ):
                    raise WorkflowError("Accepted workflows are immutable")
                if args.command == "ready":
                    print(json.dumps(planning.ready_tasks(workflow), indent=2))
                    return 0
                if args.command == "prepare-spawn":
                    payload = planning.prepare_spawn(
                        workflow, args.task_id, escalate=args.escalate
                    )
                    write_workflow(artifact_root, workflow)
                    print(json.dumps(payload, indent=2))
                    return 0
                if args.command == "run-checks":
                    workflow.pop("checkEvidence", None)
                    workflow.pop("mainReview", None)
                    write_workflow(artifact_root, workflow)
                    workflow["checkEvidence"] = evidence.run_checks(
                        workflow, args.checks_file
                    )
                    workflow.pop("mainReview", None)
                elif args.command == "record-main-review":
                    identity = evidence.main_identity(workflow["policy"]["projectRoot"])
                    checks = workflow.get("checkEvidence")
                    if (
                        not checks
                        or checks["runs"] != evidence.runs_snapshot(workflow)
                        or checks["source"]
                        != evidence.snapshot(
                            workflow["policy"]["projectRoot"],
                            workflow["policy"]["artifactRoot"],
                        )
                    ):
                        raise WorkflowError("Execute current checks before main review")
                    review = args.review_file.read_text().strip()
                    if not review:
                        raise WorkflowError(
                            "Main review must explain scope, quality and remaining risks"
                        )
                    workflow["mainReview"] = {
                        "identity": identity,
                        "text": review,
                        "checksHash": evidence.fingerprint(checks),
                    }
                elif args.command == "verify-final-inputs":
                    from .workflow import _acceptance_snapshot

                    task = workflow["tasks"][args.task_id]
                    prepared = (task.get("latestSpawn") or {}).get(
                        "prepared"
                    ) or task.get("prepared")
                    if (
                        task["role"] != "final-verifier"
                        or not prepared
                        or prepared.get("acceptanceSnapshot")
                        != _acceptance_snapshot(workflow["tasks"])
                    ):
                        raise WorkflowError("Final verifier inputs changed")
                    if prepared.get("source") != evidence.snapshot(
                        workflow["policy"]["projectRoot"],
                        workflow["policy"]["artifactRoot"],
                    ):
                        raise WorkflowError("Final verifier source changed")
                    print(
                        "Final inputs are current; main thread still owns whole-workflow acceptance."
                    )
                    return 0
                elif args.command == "register-task":
                    register_task(
                        workflow,
                        task_id=args.task_id,
                        role=args.role,
                        scopes=args.scope,
                        writable=args.writable,
                        parallel=args.parallel,
                        task_file=args.task_file,
                        model_profile=args.model_profile,
                        complexity=args.complexity,
                        review_for_task_id=args.review_for_task_id,
                        review_kind=args.review_kind,
                        depends_on=args.depends_on,
                    )
                elif args.command == "record-run":
                    record_run(
                        workflow,
                        task_id=args.task_id,
                        agent_id=args.agent_id,
                        report=args.report_file.read_text(encoding="utf-8"),
                        report_path=str(args.report_file),
                        run_id=args.run_id,
                        started_at=args.started_at,
                        transcript_path=args.transcript_path,
                    )
                elif args.command == "record-spawn":
                    record_spawn(
                        workflow,
                        task_id=args.task_id,
                        agent_id=args.agent_id,
                        actual_model=args.actual_model,
                        inherit_parent=args.inherit_parent,
                        fallback_reason=args.fallback_reason,
                    )
                elif args.command == "record-close":
                    record_close(
                        workflow,
                        task_id=args.task_id,
                        agent_id=args.agent_id,
                        status=args.status,
                        transcript_path=args.transcript_path,
                        close_transcript=args.close_transcript,
                    )
                elif args.command == "verify":
                    verify_workflow(workflow)
                path = write_workflow(artifact_root, workflow)
    except (OSError, ValueError, KeyError, WorkflowError) as error:
        parser.error(str(error))
        return 2
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
