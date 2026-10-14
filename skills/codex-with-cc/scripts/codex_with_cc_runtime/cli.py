from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

from .artifacts import resolve_artifact_root, run_verify_artifacts, run_verify_chain, run_verify_workflow, run_verify_final_inputs
from .lifecycle import configure_lifecycle, record_agent_terminal, audit_lifecycle
from .verification_supplements import run_record_verification_supplement
from .common import DelegateError, WORKER_ROLES
from .delegate import run_delegate
from .openai_compatible_report import run_openai_compatible_report_delegate
from .real_chain import run_real_chain_validation
from .selftests import run_test_runtime, run_test_session_pool
from .task_contract import run_validate_task
from .workflow import record_agent_close, record_agent_spawn
from .ccviz_parser import list_workflows, get_workflow_details
from .ccviz_renderer import render_list, render_show, render_audit
from .run_health import run_inspect_runs
from .execution_policy import configure
from .check_evidence import run_checks, run_main_review
from .routing import run_prepare_task
from .plan_cancellation import run_cancel_prepared_task
from .native_run import run_record_native
from .metrics import run_metrics



def choice_arg(choices: list[str]) -> Callable[[str], str]:
    lookup = {choice.lower(): choice for choice in choices}

    def parse(value: str) -> str:
        selected = lookup.get(value.lower())
        if selected is None:
            expected = ", ".join(choices)
            raise argparse.ArgumentTypeError(f"invalid choice: {value!r} (choose from {expected})")
        return selected

    return parse



def int_range_arg(name: str, minimum: int, maximum: int) -> Callable[[str], int]:
    def parse(value: str) -> int:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"{name} must be an integer") from exc
        if parsed < minimum or parsed > maximum:
            raise argparse.ArgumentTypeError(f"{name} must be between {minimum} and {maximum}")
        return parsed

    return parse



def add_delegate_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-TaskFile", dest="task_file", required=True)
    parser.add_argument("-Scope", dest="scope", action="append", default=[])
    parser.add_argument("-Tests", dest="tests", action="append", default=[])
    parser.add_argument("-WorkflowId", dest="workflow_id", required=True)
    parser.add_argument("-TaskId", dest="task_id", required=True)
    parser.add_argument("-Role", dest="role", type=choice_arg(list(WORKER_ROLES)), required=True)
    parser.add_argument("-ReviewForTaskId", dest="review_for_task_id")
    parser.add_argument("-ReviewForRunId", dest="review_for_run_id")
    parser.add_argument("-ReviewKind", dest="review_kind", type=choice_arg(["spec", "quality"]))
    parser.add_argument("-DependsOn", dest="depends_on", action="append", default=[])
    parser.add_argument("-Model", dest="model", default="sonnet")
    parser.add_argument("-WorkerEffort", dest="worker_effort", choices=("low", "medium", "high", "max"))
    parser.add_argument("-Name", dest="name")
    parser.add_argument("-NamePrefix", dest="name_prefix", default="codex-delegate")
    parser.add_argument("-MaxBudgetUsd", dest="max_budget_usd")
    parser.add_argument("-ArtifactRoot", dest="artifact_root")
    parser.add_argument("-OutputPath", dest="output_path")
    parser.add_argument("-AllowParallel", dest="allow_parallel", action="store_true")
    parser.add_argument("-SessionMode", dest="session_mode", type=choice_arg(["PrimaryReuse", "PrimaryAnchor", "ParallelPool"]))
    parser.add_argument("-SessionKey", dest="session_key", required=True)
    parser.add_argument("-SessionLeaseTimeoutSeconds", dest="session_lease_timeout_seconds", type=int, default=21600)
    parser.add_argument("-SessionLeaseWaitSeconds", dest="session_lease_wait_seconds", type=int, default=30)
    parser.add_argument("-ResetPrimarySession", dest="reset_primary_session", action="store_true")
    parser.add_argument("-ResetParallelPool", dest="reset_parallel_pool", action="store_true")
    parser.add_argument("-LockTimeoutSeconds", dest="lock_timeout_seconds", type=int, default=30)
    parser.add_argument("-LockPollMilliseconds", dest="lock_poll_milliseconds", type=int, default=500)
    parser.add_argument("-MaxRetryCount", dest="max_retry_count", type=int_range_arg("MaxRetryCount", 0, 100), default=1)
    parser.add_argument("-ExecutionTimeoutSeconds", dest="execution_timeout_seconds", type=int_range_arg("ExecutionTimeoutSeconds", 1, 86400))
    parser.add_argument("-SilentTimeoutSeconds", dest="silent_timeout_seconds", type=int_range_arg("SilentTimeoutSeconds", 1, 86400), default=600)
    parser.add_argument("-HeartbeatSeconds", dest="heartbeat_seconds", type=int_range_arg("HeartbeatSeconds", 1, 3600), default=15)
    parser.add_argument("-TrustedLocalFallback", dest="trusted_local_fallback", action="store_true")
    parser.add_argument("-BypassPermissions", dest="bypass_permissions", action="store_true")
    parser.add_argument("-DryRun", dest="dry_run", action="store_true")


def add_validate_task_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-TaskFile", dest="task_file", required=True)
    parser.add_argument("-Role", dest="role", type=choice_arg(list(WORKER_ROLES)), required=True)
    parser.add_argument("-ReviewForTaskId", dest="review_for_task_id")
    parser.add_argument("-ReviewForRunId", dest="review_for_run_id")
    parser.add_argument("-ReviewKind", dest="review_kind", type=choice_arg(["spec", "quality"]))
    parser.add_argument("-Tests", dest="tests", action="append", default=[])



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex_with_cc scripts", allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)
    metrics = sub.add_parser("workflow-metrics", allow_abbrev=False)
    metrics.add_argument("-WorkflowId", dest="workflow_id", required=True)
    metrics.add_argument("-ArtifactRoot", dest="artifact_root")
    metrics.set_defaults(func=run_metrics)
    policy = sub.add_parser("configure-workflow", allow_abbrev=False)
    policy.add_argument("-WorkflowId", dest="workflow_id", required=True)
    policy.add_argument("-ArtifactRoot", dest="artifact_root")
    policy.add_argument("-ProjectRoot", dest="project_root", required=True)
    policy.add_argument("-Profile", dest="profile", choices=("standard", "strict"), default="standard")
    policy.add_argument("-MaxParallel", dest="max_parallel", type=int_range_arg("MaxParallel", 1, 64))
    policy.add_argument("-MainScope", dest="main_scope", action="append", default=[])
    policy.add_argument("-CarrierModel", dest="carrier_model", default="gpt-5.6-luna")
    policy.add_argument("-CarrierEffort", dest="carrier_effort", default="low")
    policy.add_argument("-WorkerModel", dest="worker_model", default="sonnet")
    policy.add_argument("-NativeModel", dest="native_model", default="gpt-6-astra")
    policy.add_argument("-NativeEffort", dest="native_effort", default="high")
    policy.set_defaults(func=configure)

    checks = sub.add_parser("run-checks", allow_abbrev=False)
    checks.add_argument("-WorkflowId", dest="workflow_id", required=True)
    checks.add_argument("-ArtifactRoot", dest="artifact_root")
    checks.add_argument("-ChecksFile", dest="checks_file", required=True)
    checks.add_argument("-InputScope", dest="input_scope", action="append", default=[])
    checks.add_argument("-ScopeReason", dest="scope_reason")
    checks.set_defaults(func=run_checks)

    review = sub.add_parser("record-main-review", allow_abbrev=False)
    review.add_argument("-WorkflowId", dest="workflow_id", required=True)
    review.add_argument("-ArtifactRoot", dest="artifact_root")
    review.add_argument("-EvidenceFile", dest="evidence_file", required=True)
    review.add_argument("-ReviewFile", dest="review_file", required=True)
    review.add_argument("-DecisionsFile", dest="decisions_file")
    review.set_defaults(func=run_main_review)

    prepare = sub.add_parser("prepare-task", allow_abbrev=False)
    prepare.add_argument("-WorkflowId", dest="workflow_id", required=True)
    prepare.add_argument("-TaskId", dest="task_id", required=True)
    prepare.add_argument("-ArtifactRoot", dest="artifact_root")
    prepare.add_argument("-Backend", dest="backend", choices=("claude-code", "claude-process", "codex-native"), required=True)
    prepare.add_argument("-Role", dest="role", choices=WORKER_ROLES, required=True)
    prepare.add_argument("-TaskFile", dest="task_file", required=True)
    prepare.add_argument("-Scope", dest="scope", action="append", default=[])
    prepare.add_argument("-Tests", dest="tests", action="append", default=[])
    prepare.add_argument("-SessionKey", dest="session_key")
    prepare.add_argument("-AllowParallel", dest="allow_parallel", action="store_true")
    prepare.add_argument("-BypassPermissions", dest="bypass_permissions", action="store_true")
    prepare.add_argument("-ReviewForTaskId", dest="review_for_task_id")
    prepare.add_argument("-ReviewForRunId", dest="review_for_run_id")
    prepare.add_argument("-ReviewKind", dest="review_kind", choices=("spec", "quality"))
    for flag, dest in (("CarrierModel", "carrier_model"), ("WorkerModel", "worker_model"), ("NativeModel", "native_model")):
        prepare.add_argument("-" + flag, dest=dest)
    for flag, dest in (("CarrierEffort", "carrier_effort"), ("NativeEffort", "native_effort")):
        prepare.add_argument("-" + flag, dest=dest, choices=("low", "medium", "high", "xhigh", "max", "ultra"))
    prepare.add_argument("-WorkerEffort", dest="worker_effort", choices=("low", "medium", "high", "max"))
    prepare.add_argument("-DecisionReason", dest="decision_reason")
    prepare.add_argument("-Complexity", dest="complexity", choices=("simple", "normal", "complex", "high-risk"), default="normal")
    prepare.add_argument("-ReadScope", dest="read_scope", action="append", default=[])
    prepare.add_argument("-InputsComplete", dest="inputs_complete", action="store_true")
    prepare.add_argument("-DependsOn", dest="depends_on", action="append", default=[])
    prepare.add_argument("-MaxBudgetUsd", dest="max_budget_usd")
    prepare.add_argument("-AllowedCommandsFile", dest="allowed_commands_file")
    prepare.add_argument("-ExecutionTimeoutSeconds", dest="execution_timeout_seconds", type=int_range_arg("ExecutionTimeoutSeconds", 1, 86400), help="claude-process only; default 900 seconds")
    prepare.add_argument("-Admit", dest="admit", action="store_true", help="Prepare then atomically admit; blocked plans remain queued")
    prepare.set_defaults(func=run_prepare_task)

    from .process_run import run_validate_process_launch
    process_validation = sub.add_parser("validate-process-launch", allow_abbrev=False)
    process_validation.add_argument("-LaunchDirectory", dest="launch_directory", required=True)
    process_validation.set_defaults(func=run_validate_process_launch)

    from .adaptive import run_ready, run_admit, run_advice
    ready = sub.add_parser("ready-tasks", allow_abbrev=False)
    ready.add_argument("-WorkflowId", dest="workflow_id", required=True)
    ready.add_argument("-ArtifactRoot", dest="artifact_root", required=True)
    ready.set_defaults(func=run_ready)
    admit = sub.add_parser("admit-task", allow_abbrev=False)
    admit.add_argument("-PlanFile", dest="plan_file", required=True)
    admit.set_defaults(func=run_admit)
    advice = sub.add_parser("advise-task", allow_abbrev=False)
    advice.add_argument("-Complexity", dest="complexity", choices=("simple", "normal", "complex", "high-risk"), default="normal")
    advice.add_argument("-Independent", dest="independent", action="store_true")
    advice.add_argument("-Coupled", dest="coupled", action="store_true")
    advice.add_argument("-EstimatedMinutes", dest="estimated_minutes", type=float, default=10)
    advice.add_argument("-OverheadMinutes", dest="overhead_minutes", type=float, default=2)
    advice.add_argument("-WorkKind", dest="work_kind", choices=("development", "decision", "discussion"), default="development")
    advice.add_argument("-SmallKnownTask", dest="small_known_task", action="store_true", help="Main judges the work to be small, known and low-risk")
    advice.set_defaults(func=run_advice)

    cancel = sub.add_parser("cancel-prepared-task", allow_abbrev=False,
                            help="Withdraw an undispatched plan with a reason and audit receipt")
    cancel.add_argument("-PlanFile", dest="plan_file", required=True)
    cancel.add_argument("-Reason", dest="reason", required=True)
    cancel.set_defaults(func=run_cancel_prepared_task)

    native = sub.add_parser("record-native-run", allow_abbrev=False)
    native.add_argument("-PlanFile", dest="plan_file", required=True)
    native.add_argument("-AgentId", dest="agent_id", required=True)
    native.add_argument("-TranscriptPath", dest="transcript_path", required=True)
    native.add_argument("-Settle", dest="settle", action="store_true", help="Also record verified terminal-evidence settlement")
    native.set_defaults(func=run_record_native)

    from .packets import run_review_packet
    packet = sub.add_parser("review-packet", allow_abbrev=False)
    packet.add_argument("-WorkflowId", dest="workflow_id", required=True)
    packet.add_argument("-ArtifactRoot", dest="artifact_root")
    packet.add_argument("-Limit", dest="limit", type=int_range_arg("Limit", 1, 100), default=20)
    packet.set_defaults(func=run_review_packet)
    health = sub.add_parser("inspect-runs", allow_abbrev=False)
    health.add_argument("-ArtifactRoot", dest="artifact_root")
    health.add_argument("-WorkflowId", dest="workflow_id")
    health.set_defaults(func=run_inspect_runs)
    delegate = sub.add_parser("delegate", allow_abbrev=False)
    add_delegate_args(delegate)
    delegate.set_defaults(func=run_delegate)

    report = sub.add_parser("openai-compatible-report", allow_abbrev=False)
    add_delegate_args(report)
    report.set_defaults(func=run_openai_compatible_report_delegate, model="deepseek-v4-flash")

    validate_task = sub.add_parser("validate-task", allow_abbrev=False)
    add_validate_task_args(validate_task)
    validate_task.set_defaults(func=run_validate_task)

    verify = sub.add_parser("verify-artifacts", allow_abbrev=False)
    verify.add_argument("-RunId", dest="run_id", required=True)
    verify.add_argument("-ArtifactRoot", dest="artifact_root")
    verify.set_defaults(func=run_verify_artifacts)

    verify_run = sub.add_parser("verify-run", allow_abbrev=False)
    verify_run.add_argument("-RunId", dest="run_id", required=True)
    verify_run.add_argument("-ArtifactRoot", dest="artifact_root")
    verify_run.set_defaults(func=run_verify_artifacts)

    workflow = sub.add_parser("verify-workflow", allow_abbrev=False)
    workflow.add_argument("-WorkflowId", dest="workflow_id", required=True)
    workflow.add_argument("-ArtifactRoot", dest="artifact_root")
    workflow.set_defaults(func=run_verify_workflow)

    inputs = sub.add_parser("verify-final-inputs", allow_abbrev=False)
    inputs.add_argument("-WorkflowId", dest="workflow_id", required=True)
    inputs.add_argument("-ArtifactRoot", dest="artifact_root")
    inputs.set_defaults(func=run_verify_final_inputs)

    supplement = sub.add_parser("record-verification-supplement", allow_abbrev=False)
    supplement.add_argument("-RunId", dest="run_id", required=True)
    supplement.add_argument("-ArtifactRoot", dest="artifact_root")
    supplement.set_defaults(func=run_record_verification_supplement)

    lifecycle = sub.add_parser("configure-lifecycle", allow_abbrev=False)
    lifecycle.add_argument("-WorkflowId", dest="workflow_id", required=True)
    lifecycle.add_argument("-ArtifactRoot", dest="artifact_root")
    lifecycle.add_argument("-Policy", dest="policy", choices=("strict-close", "terminal-evidence", "process-exit"), required=True)
    lifecycle.add_argument("-HostToolsFile", dest="host_tools_file", required=True)
    lifecycle.add_argument("-MigrateExisting", dest="migrate_existing", action="store_true")
    lifecycle.set_defaults(func=run_configure_lifecycle)

    terminal = sub.add_parser("record-agent-terminal", allow_abbrev=False)
    terminal.add_argument("-WorkflowId", dest="workflow_id", required=True)
    terminal.add_argument("-TaskId", dest="task_id", required=True)
    terminal.add_argument("-AgentId", dest="agent_id", required=True)
    terminal.add_argument("-TranscriptPath", dest="transcript_path", required=True)
    terminal.add_argument("-ArtifactRoot", dest="artifact_root")
    terminal.set_defaults(func=run_record_agent_terminal)

    audit = sub.add_parser("audit-lifecycle", allow_abbrev=False)
    audit.add_argument("-WorkflowId", dest="workflow_id", required=True)
    audit.add_argument("-ArtifactRoot", dest="artifact_root")
    audit.set_defaults(func=run_audit_lifecycle)

    record_spawn = sub.add_parser("record-agent-spawn", allow_abbrev=False)
    record_spawn.add_argument("-WorkflowId", dest="workflow_id", required=True)
    record_spawn.add_argument("-TaskId", dest="task_id", required=True)
    record_spawn.add_argument("-AgentId", dest="agent_id", required=True)
    record_spawn.add_argument("-ArtifactRoot", dest="artifact_root")
    record_spawn.set_defaults(func=run_record_agent_spawn)

    record_close = sub.add_parser("record-agent-close", allow_abbrev=False)
    record_close.add_argument("-WorkflowId", dest="workflow_id", required=True)
    record_close.add_argument("-TaskId", dest="task_id", required=True)
    record_close.add_argument("-AgentId", dest="agent_id", required=True)
    record_close.add_argument("-ArtifactRoot", dest="artifact_root")
    record_close.set_defaults(func=run_record_agent_close)

    chain = sub.add_parser("verify-chain", allow_abbrev=False)
    chain.add_argument("-ArtifactRoot", dest="artifact_root", required=True)
    chain.add_argument("-SessionKey", dest="session_key", required=True)
    chain.add_argument("-AnchorRunId", dest="anchor_run_id", required=True)
    chain.add_argument("-ParallelRunIds", dest="parallel_run_ids", nargs="+", required=True)
    chain.add_argument("-ReuseRunIds", dest="reuse_run_ids", nargs="+", required=True)
    chain.set_defaults(func=run_verify_chain)

    validation = sub.add_parser("run-real-chain-validation", allow_abbrev=False)
    validation.add_argument("-ValidationRoot", dest="validation_root")
    validation.add_argument("-Name", dest="name")
    validation.add_argument("-SessionKey", dest="session_key")
    validation.set_defaults(func=run_real_chain_validation)

    sub.add_parser("test-runtime").set_defaults(func=run_test_runtime)
    sub.add_parser("test-session-pool").set_defaults(func=run_test_session_pool)

    # ccviz subcommands
    ccviz = sub.add_parser("ccviz", allow_abbrev=False)
    ccviz_sub = ccviz.add_subparsers(dest="ccviz_command", required=True)
    
    ccviz_list = ccviz_sub.add_parser("list", allow_abbrev=False)
    ccviz_list.add_argument("-ArtifactRoot", dest="artifact_root")
    ccviz_list.set_defaults(func=run_ccviz_list)
    
    ccviz_show = ccviz_sub.add_parser("show", allow_abbrev=False)
    ccviz_show.add_argument("workflow_id")
    ccviz_show.add_argument("-ArtifactRoot", dest="artifact_root")
    ccviz_show.set_defaults(func=run_ccviz_show)
    
    ccviz_audit = ccviz_sub.add_parser("audit", allow_abbrev=False)
    ccviz_audit.add_argument("workflow_id")
    ccviz_audit.add_argument("-ArtifactRoot", dest="artifact_root")
    ccviz_audit.set_defaults(func=run_ccviz_audit)

    return parser


def run_ccviz_list(ns: argparse.Namespace) -> int:
    workflows = list_workflows(ns.artifact_root)
    render_list(workflows)
    return 0


def run_record_agent_spawn(ns: argparse.Namespace) -> int:
    root = resolve_artifact_root(ns.artifact_root, workflow_id=ns.workflow_id)
    path = record_agent_spawn(root, ns.workflow_id, ns.task_id, ns.agent_id)
    print(f"Recorded agent spawn: {ns.agent_id} -> {path}")
    return 0


def run_configure_lifecycle(ns: argparse.Namespace) -> int:
    root = resolve_artifact_root(ns.artifact_root, workflow_id=ns.workflow_id)
    path = configure_lifecycle(root, ns.workflow_id, ns.policy, Path(ns.host_tools_file), ns.migrate_existing)
    print(f"Lifecycle configured: {ns.policy} -> {path}")
    return 0


def run_record_agent_terminal(ns: argparse.Namespace) -> int:
    root = resolve_artifact_root(ns.artifact_root, workflow_id=ns.workflow_id)
    path = record_agent_terminal(root, ns.workflow_id, ns.task_id, ns.agent_id, Path(ns.transcript_path))
    print(f"Recorded execution terminal evidence (not thread closure): {ns.agent_id} -> {path}")
    return 0


def run_audit_lifecycle(ns: argparse.Namespace) -> int:
    import json
    root = resolve_artifact_root(ns.artifact_root, workflow_id=ns.workflow_id)
    result = audit_lifecycle(root, ns.workflow_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if all(item["eligible"] for item in result["attempts"]) else 1


def run_record_agent_close(ns: argparse.Namespace) -> int:
    root = resolve_artifact_root(ns.artifact_root, workflow_id=ns.workflow_id)
    path = record_agent_close(root, ns.workflow_id, ns.task_id, ns.agent_id)
    print(f"Recorded agent close: {ns.agent_id} -> {path}")
    return 0


def run_ccviz_show(ns: argparse.Namespace) -> int:
    wf = get_workflow_details(ns.workflow_id, ns.artifact_root)
    if not wf:
        print(f"\033[91mError: Workflow '{ns.workflow_id}' not found.\033[0m", file=sys.stderr)
        return 1
    render_show(wf)
    return 0


def run_ccviz_audit(ns: argparse.Namespace) -> int:
    wf = get_workflow_details(ns.workflow_id, ns.artifact_root)
    if not wf:
        print(f"\033[91mError: Workflow '{ns.workflow_id}' not found.\033[0m", file=sys.stderr)
        return 1
    render_audit(wf)
    return 0



def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    try:
        return int(ns.func(ns))
    except DelegateError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
