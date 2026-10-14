"""Behavioral regressions for main-owned dispatch and evidence-based acceptance."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests.test_execution_profiles import project, run, native_complete, checks, main_review, carrier_log
from tests.test_plan_cancellation import set_actor
from tests.task_helpers import compliant_task
from tests.test_workflow_contract import workflow_report
from tests.test_platform_hooks import run_hook
from codex_with_cc_runtime import workflow, lifecycle, fixed_launcher
from codex_with_cc_runtime.common import DelegateError
from codex_with_cc_runtime.io_utils import load_json
from codex_with_cc_runtime.routing import verified_plan, spawn_payload
from codex_with_cc_runtime.reports import text_has_required_report_headings, report_section


def prepare(project, tid="impl", role="implementer", scope="app.py", *extra):
    _, root = project
    task = root / (tid + "-input.md"); task.write_text(compliant_task("Inspect assigned files and return actual findings."))
    run("prepare-task", "-WorkflowId", "new", "-TaskId", tid, "-ArtifactRoot", str(root),
        "-TaskFile", str(task), "-Role", role, "-Backend", "codex-native", "-Scope", scope, *extra)
    return Path(list(load_json(workflow.workflow_path(root, "new"))["preparedTasks"].values())[-1]["path"])


def adaptive(project, monkeypatch, slots=2, *extra):
    p, root = project; set_actor(project, monkeypatch)
    run("configure-workflow", "-WorkflowId", "new", "-ProjectRoot", str(p), "-ArtifactRoot", str(root),
        "-MaxParallel", str(slots), *extra)


def verify(project):
    return run("verify-workflow", "-WorkflowId", "new", "-ArtifactRoot", str(project[1]))


def test_ready_wave_and_dependency_progress_without_waiting_for_unrelated_child(project, monkeypatch, capsys):
    adaptive(project, monkeypatch)
    a = prepare(project, "a", "implementer", "app.py", "-AllowParallel")
    b = prepare(project, "b", "researcher", "other.py", "-AllowParallel")
    c = prepare(project, "c", "researcher", "app.py", "-AllowParallel", "-DependsOn", "a")
    capsys.readouterr(); run("ready-tasks", "-WorkflowId", "new", "-ArtifactRoot", str(project[1]))
    ready = json.loads(capsys.readouterr().out)
    assert [x["taskId"] for x in ready["ready"]] == ["a", "b"]
    assert load_json(c)["planId"] in ready["blocked"]
    for path in (a, b): run("admit-task", "-PlanFile", str(path))
    with pytest.raises(DelegateError): run("admit-task", "-PlanFile", str(c))
    native_complete(project, monkeypatch, a)
    assert run("admit-task", "-PlanFile", str(c)) == 0
    # b is still reserved; c may begin because only a is a dependency.
    w = load_json(workflow.workflow_path(project[1], "new"))
    assert not w["preparedTasks"][load_json(b)["planId"]].get("runId")


@pytest.mark.parametrize("role,scope,extra,blocked", [
    ("researcher", "app.py", (), True),
    ("implementer", "different.py", ("-ReadScope", "app.py"), True),
    ("implementer", "different.py", (), False),
])
def test_dispatch_checks_read_write_conflicts(project, monkeypatch, role, scope, extra, blocked):
    adaptive(project, monkeypatch)
    a = prepare(project, "a", "implementer", "app.py", "-AllowParallel")
    b = prepare(project, "b", role, scope, "-AllowParallel", *extra)
    run("admit-task", "-PlanFile", str(a))
    if blocked:
        with pytest.raises(DelegateError, match="scope"): run("admit-task", "-PlanFile", str(b))
    else:
        assert run("admit-task", "-PlanFile", str(b)) == 0


def test_readers_can_share_scope_but_main_reserved_scope_blocks(project, monkeypatch):
    adaptive(project, monkeypatch, 3, "-MainScope", "main")
    for tid in ("a", "b"):
        path = prepare(project, tid, "researcher", "app.py", "-AllowParallel")
        assert run("admit-task", "-PlanFile", str(path)) == 0
    main = prepare(project, "main", "researcher", "main/config.json", "-AllowParallel")
    with pytest.raises(DelegateError, match="reserved"): run("admit-task", "-PlanFile", str(main))


def test_parallel_admissions_cannot_overbook_last_slot(project, monkeypatch):
    adaptive(project, monkeypatch, 1)
    paths = [prepare(project, x, "researcher", x, "-AllowParallel") for x in ("a", "b")]
    def try_admit(path):
        try: return run("admit-task", "-PlanFile", str(path))
        except DelegateError: return "blocked"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(try_admit, paths))
    assert results.count(0) == 1 and results.count("blocked") == 1


def test_queued_plan_is_rejected_by_hook_import_and_launcher_until_admitted(project, monkeypatch):
    adaptive(project, monkeypatch)
    path = prepare(project, "impl", "implementer", "app.py", "-Backend", "claude-code")
    p = load_json(path); payload = spawn_payload(path, p)["spawn"]
    assert run_hook({"hook_event_name": "PreToolUse", "tool_name": "spawn_agent", "tool_input": payload})["hookSpecificOutput"]["permissionDecision"] == "deny"
    with pytest.raises(DelegateError, match="admission"): verified_plan(path)
    with pytest.raises(DelegateError, match="admission"): fixed_launcher.claim_descriptor(path.parent)
    assert run("admit-task", "-PlanFile", str(path)) == 0
    assert run_hook({"hook_event_name": "PreToolUse", "tool_name": "spawn_agent", "tool_input": payload}) == {}
    with pytest.raises(DelegateError, match="already admitted"): run("admit-task", "-PlanFile", str(path))


def test_model_effort_budget_are_task_specific_and_immutable(project, monkeypatch):
    from codex_with_cc_runtime.claude_cli import new_claude_cli_args
    path = prepare(project, "impl", "implementer", "app.py", "-Backend", "claude-code", "-WorkerModel", "opus",
                   "-WorkerEffort", "low", "-CarrierModel", "gpt-6-astra", "-CarrierEffort", "medium",
                   "-MaxBudgetUsd", "0.4", "-DecisionReason", "Small mechanical edit; preserve explicit carrier choice.")
    p = load_json(path)
    launch = load_json(path.parent / "launch.json")
    assert p["model"] == "gpt-6-astra" and launch["model"] == "opus" and launch["workerEffort"] == "low"
    args = fixed_launcher.build_delegate_args(launch)
    assert args[args.index("-WorkerEffort") + 1] == "low" and args[args.index("-MaxBudgetUsd") + 1] == "0.4"
    cli = new_claude_cli_args("opus", "test", "implementer", "session", False, "0.4", False, effort="low")
    assert cli[cli.index("--effort") + 1] == "low"
    w = load_json(workflow.workflow_path(project[1], "new"))
    assert w["executionPolicy"]["carrierModel"] == "gpt-5.6-luna"
    path.write_text(path.read_text().replace('"low"', '"high"'))
    with pytest.raises(DelegateError, match="changed"): verified_plan(path)


def test_native_effort_override_requires_actual_host_match(project, monkeypatch):
    path = prepare(project, "impl", "implementer", "app.py", "-NativeEffort", "low", "-DecisionReason", "Simple bounded work.")
    with pytest.raises(DelegateError, match="reasoning effort"):
        native_complete(project, monkeypatch, path, actual_effort="high")


@pytest.mark.parametrize("status", ["DONE_WITH_CONCERNS", "BLOCKED", "NEEDS_CONTEXT", "FAIL"])
def test_only_nonblocking_concerns_can_be_accepted_with_pinned_decisions(project, monkeypatch, status):
    path = prepare(project)
    report = workflow_report(role="implementer").replace("\nDONE\n", "\n" + status + "\n")
    native_complete(project, monkeypatch, path, report=report)
    evidence = checks(project)
    with pytest.raises(DelegateError): main_review(project, monkeypatch, evidence)
    _, root = project; w = load_json(workflow.workflow_path(root, "new")); rid = w["tasks"]["impl"]["latestRunId"]
    config = load_json(Path(w["runs"][rid]["configPath"]))
    decisions = root / "decisions-input.json"
    decisions.write_text(json.dumps({"decisions": [{"taskId": "impl", "runId": rid,
        "reportSha256": lifecycle.digest(Path(config["outputPath"])), "concerns": [{"finding": "Only local coverage available.",
        "disposition": "accepted-risk", "reason": "Scope is a local-only tool change.", "evidence": str(evidence)}]}]}))
    args = ("record-main-review", "-WorkflowId", "new", "-ArtifactRoot", str(root), "-EvidenceFile", str(evidence),
            "-ReviewFile", str(root / "review.md"), "-DecisionsFile", str(decisions))
    if status != "DONE_WITH_CONCERNS":
        with pytest.raises(DelegateError): run(*args)
        return
    assert run(*args) == 0 and verify(project) == 0
    assert Path(config["outputPath"]).read_text() == report
    w = load_json(workflow.workflow_path(root, "new"))
    assert w["tasks"]["impl"]["lastReportStatus"] == status
    Path(w["mainReview"]["concernDecisions"]["path"]).write_text('{}')
    with pytest.raises(DelegateError, match="decisions"): verify(project)


def test_scoped_checks_preserve_unrelated_changes_but_invalidate_dependencies(project, monkeypatch):
    p, root = project; (p / "shared.py").write_text("dependency = 1\n")
    path = prepare(project, "impl", "implementer", "app.py", "-ReadScope", "shared.py", "-InputsComplete",
                   "-DecisionReason", "app.py and shared.py are the complete inputs for this isolated fixture.")
    native_complete(project, monkeypatch, path)
    checks(project)
    assert run("run-checks", "-WorkflowId", "new", "-ArtifactRoot", str(root), "-ChecksFile", str(root / "checks-input.json"),
               "-InputScope", "app.py", "-ScopeReason", "No other dependencies in this fixture.") == 0
    evidence = next(f for f in (root / "checks").glob('*/evidence.json') if load_json(f).get('snapshotPolicy'))
    assert main_review(project, monkeypatch, evidence) == 0
    (p / "unrelated.md").write_text("Other task updated docs.")
    assert verify(project) == 0
    (p / "shared.py").write_text("dependency = 2\n")
    with pytest.raises(DelegateError, match="stale"): verify(project)


def test_unknown_dependencies_keep_full_project_checks(project, monkeypatch):
    native_complete(project, monkeypatch, prepare(project))
    _, root = project; checks(project)
    with pytest.raises(DelegateError, match="not declared complete"):
        run("run-checks", "-WorkflowId", "new", "-ArtifactRoot", str(root), "-ChecksFile", str(root / "checks-input.json"),
            "-InputScope", "app.py", "-ScopeReason", "Only app.py")


def test_report_formatting_is_flexible_but_ambiguous_reports_are_rejected():
    report = workflow_report(role="implementer")
    decorated = "Summary first is okay.\n" + report.replace("Status\n", "**status**:\n").replace("Role\n", "## ROLE\n")
    assert text_has_required_report_headings(decorated)
    assert report_section(decorated, "Status") == "DONE"
    assert not text_has_required_report_headings(report + "\nStatus\nFAIL\n")
    assert not text_has_required_report_headings("```\n" + report + "\n```\n")


def test_rerun_invalidates_current_dependents_but_preserves_old_attempts(project, monkeypatch):
    from codex_with_cc_runtime.adaptive import require_current_dependencies
    adaptive(project, monkeypatch)
    a = prepare(project, "a")
    run("admit-task", "-PlanFile", str(a)); native_complete(project, monkeypatch, a)
    b = prepare(project, "b", "researcher", "app.py", "-DependsOn", "a")
    run("admit-task", "-PlanFile", str(b)); native_complete(project, monkeypatch, b)
    assert main_review(project, monkeypatch, checks(project)) == 0 and verify(project) == 0
    new_a = prepare(project, "a")
    run("admit-task", "-PlanFile", str(new_a)); native_complete(project, monkeypatch, new_a)
    p, w = verified_plan(b)  # Old evidence still describes a real earlier attempt.
    with pytest.raises(DelegateError, match="stale"): require_current_dependencies(p, w)
    new_b = prepare(project, "b", "researcher", "app.py", "-DependsOn", "a")
    run("admit-task", "-PlanFile", str(new_b)); native_complete(project, monkeypatch, new_b)
    assert main_review(project, monkeypatch, checks(project)) == 0 and verify(project) == 0
    assert len(load_json(workflow.workflow_path(project[1], "new"))["runs"]) == 4


def test_scoped_checks_reject_symlink_and_escaping_inputs(project, monkeypatch):
    p, root = project
    with pytest.raises(DelegateError, match="Scope"): prepare(project, "bad", "implementer", "../outside")
    path = prepare(project, "impl", "implementer", "app.py", "-InputsComplete", "-DecisionReason", "Only app.py is needed.")
    native_complete(project, monkeypatch, path); checks(project)
    (p / "app.py").unlink(); (p / "app.py").symlink_to(root / "input-not-source")
    with pytest.raises(DelegateError, match="symlink"):
        run("run-checks", "-WorkflowId", "new", "-ArtifactRoot", str(root), "-ChecksFile", str(root / "checks-input.json"),
            "-InputScope", "app.py", "-ScopeReason", "Isolated fixture")


def test_prepared_claude_effort_budget_cross_the_actual_launcher(project, monkeypatch, tmp_path):
    import os, sys, subprocess
    from tests.test_superpowers_workflow_overhaul import make_fake_claude_bin
    from codex_with_cc_runtime.common import now_iso
    path = prepare(project, "impl", "implementer", "app.py", "-Backend", "claude-code", "-WorkerEffort", "low",
                   "-MaxBudgetUsd", "0.5", "-DecisionReason", "Small offline integration fixture")
    log = carrier_log(project, monkeypatch)
    workflow.record_agent_spawn(project[1], "new", "impl", "/root/carrier")
    fake = make_fake_claude_bin(tmp_path, "implementer", "- local fixture check passed")
    captured_args = tmp_path / "actual-args.txt"
    executable = fake / "claude"
    executable.write_text(executable.read_text().replace('cat >/dev/null', 'printf "%s\\n" "$@" > "$CC_FIXTURE_ARGS"\ncat >/dev/null'))
    scripts = Path(__file__).resolve().parents[1] / "skills/codex-with-cc/scripts"
    env = {**os.environ, "PATH": str(fake) + os.pathsep + os.environ.get("PATH", ""), "CC_FIXTURE_ARGS": str(captured_args)}
    result = subprocess.run([sys.executable, str(scripts / "fixed_launcher.py")], cwd=path.parent,
                            env=env, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    w = load_json(workflow.workflow_path(project[1], "new")); rid = w["tasks"]["impl"]["latestRunId"]
    config = load_json(project[1] / f"config_{rid}.json")
    assert config["claudeEffort"] == "low" and config["maxBudgetUsd"] == "0.5"
    actual = captured_args.read_text().splitlines()
    assert actual[actual.index("--effort") + 1] == "low" and actual[actual.index("--max-budget-usd") + 1] == "0.5"
    with log.open("a") as f:
        f.write(json.dumps({"type": "event_msg", "timestamp": now_iso(), "payload": {"type": "task_complete", "turn_id": "carrier-turn"}}) + "\n")
    lifecycle.record_agent_terminal(project[1], "new", "impl", "/root/carrier", log)
    assert main_review(project, monkeypatch, checks(project)) == 0 and verify(project) == 0


@pytest.mark.parametrize("flag,value", [("-WorkerEffort", "low"), ("-CarrierModel", "gpt-6-astra")])
def test_inapplicable_model_choices_are_not_silently_ignored(project, flag, value):
    with pytest.raises(DelegateError, match="does not apply"):
        prepare(project, "impl", "implementer", "app.py", flag, value, "-DecisionReason", "Requested choice")


def test_symlink_cannot_hide_parallel_write_conflict(project, monkeypatch):
    adaptive(project, monkeypatch)
    p, _ = project
    (p / "alias.py").symlink_to(p / "app.py")
    with pytest.raises(DelegateError, match="symlink"):
        prepare(project, "alias", "implementer", "alias.py", "-AllowParallel")
