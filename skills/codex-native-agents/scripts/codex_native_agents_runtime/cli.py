from __future__ import annotations

import argparse
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


DEFAULT_ARTIFACT_ROOT = Path(".codex/codex_native_agents/workflows")


def _add_artifact_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--artifact-root", type=Path, default=argparse.SUPPRESS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record and verify native Codex agent workflows")
    _add_artifact_root(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init")
    _add_artifact_root(init)
    init.add_argument("--workflow-id", required=True)

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
    register.add_argument("--model-profile")
    register.add_argument("--complexity", default="normal")
    register.add_argument("--review-for-task-id")
    register.add_argument("--review-kind")

    record = subparsers.add_parser("record-run")
    _add_artifact_root(record)
    record.add_argument("--workflow-id", required=True)
    record.add_argument("--task-id", required=True)
    record.add_argument("--agent-id", required=True)
    record.add_argument("--report-file", type=Path, required=True)
    record.add_argument("--run-id")
    record.add_argument("--started-at")

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

    verify = subparsers.add_parser("verify")
    _add_artifact_root(verify)
    verify.add_argument("--workflow-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    artifact_root = getattr(args, "artifact_root", DEFAULT_ARTIFACT_ROOT)
    try:
        if args.command == "validate-task":
            validate_task_file(args.task_file, args.role)
            print(args.task_file)
            return 0
        with workflow_lock(artifact_root, args.workflow_id):
            if args.command == "init":
                if workflow_path(artifact_root, args.workflow_id).exists():
                    raise WorkflowError(f"Workflow already exists: {args.workflow_id}")
                path = write_workflow(artifact_root, new_workflow(args.workflow_id))
            else:
                workflow = load_workflow(artifact_root, args.workflow_id)
                if args.command == "register-task":
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
                    )
                elif args.command == "verify":
                    verify_workflow(workflow)
                path = write_workflow(artifact_root, workflow)
    except (OSError, ValueError, WorkflowError) as error:
        parser.error(str(error))
        return 2
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
