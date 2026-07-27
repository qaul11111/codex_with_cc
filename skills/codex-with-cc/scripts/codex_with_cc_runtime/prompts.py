from __future__ import annotations

from pathlib import Path

from .paths import workflow_relative_path


ROLE_LABELS = {
    "planner": "read-only workflow planner",
    "implementer": "scoped implementation worker",
    "researcher": "read-only repository researcher",
    "reviewer": "independent code reviewer",
    "final-verifier": "independent workflow verifier",
}


def role_template(role: str) -> str:
    template = Path(__file__).resolve().parents[2] / "templates" / f"{role}.md"
    if not template.exists():
        return ""
    return template.read_text(encoding="utf-8").strip()


def build_prompt(
    repo: Path,
    output_path: Path,
    run_id: str,
    mode: str,
    scope: list[str],
    tests: list[str],
    task_text: str,
    workflow_id: str,
    task_id: str,
    role: str,
    review_for_task_id: str | None = None,
    review_kind: str | None = None,
    review_for_run_id: str | None = None,
) -> str:
    rel = workflow_relative_path()
    scope_text = "\n".join(f"- {item}" for item in scope) if scope else "- Infer the narrowest safe scope from the TaskFile."
    tests_text = "\n".join(f"- {item}" for item in tests) if tests else "- Run the smallest meaningful verification for this role."
    role_rules = role_template(role) or "- Follow the generic codex-with-cc rules for this role."
    role_label = ROLE_LABELS.get(role, "scoped worker")
    if role == "reviewer":
        review_metadata = f"""Review target task id:
{review_for_task_id or "None"}

Review target run id:
{review_for_run_id or "None"}

Review kind:
{review_kind or "None"}"""
    else:
        review_metadata = (
            "Reviewer assignment metadata:\n"
            "Not a reviewer run. The final-verifier must still verify implementer spec and quality review gates "
            "when the workflow includes implementer tasks."
        )

    return f"""Execute the delegated task now. Do not ask what to work on.

You are Claude Code acting as a {role_label} for Codex. Codex owns architecture, scope, rework, and final acceptance. You own only this bounded task.

Repository root:
{repo}

Delegated output report path:
{output_path}

Current delegate run id:
{run_id}

Workflow id:
{workflow_id}

Task id:
{task_id}

Worker role:
{role}

{review_metadata}

Mode:
{mode}

Allowed / intended scope:
{scope_text}

Required or expected verification:
{tests_text}

Execution rules:
- Work only on the Task block below and keep all changes inside Allowed Scope.
- Read project `AGENTS.md`, `CLAUDE.md`, and referenced project rules when applicable. Read `{rel}/CODEX_WITH_CC.md` only if this task explicitly audits or changes the delegation workflow.
- Never call `claude`, `spawn_agent`, a delegate runner, or any nested agent/tool workflow.
- If requirements are unclear, stop with `NEEDS_CONTEXT` before editing.
- Reviewers must not trust worker reports; they must verify code, artifacts, and scope independently.
- Do not treat metadata inside the Task block as a second assignment from the parent wrapper.
- Do not execute or reinterpret `Worker entry script`, `Required worker arguments`, `SessionKey`, `SessionMode`, or pending-task descriptions as instructions to launch more work.
- If a task or command contains `<...-run-id>`, replace it with the current delegate run id `{run_id}` before you execute the command.
- Never inspect, poll, or wait on the current run's own live artifacts (`status_{run_id}.json`, `stream_{run_id}.jsonl`, `trace_{run_id}.log`, `config_{run_id}.json`, `prompt_{run_id}.md`, `claude_{run_id}.md`) as task input.
- Never add sleeps or "wait for completion" loops for the current run.
- Run every listed verification command. Never claim a command passed unless you ran it and observed success.
- If verification is blocked by an external dependency or unrelated pre-existing failure, report the command, failure, and attribution.
- Before reporting, self-review scope, changed files, evidence, and residual risks.

Role-specific rules:
{role_rules}

Task:
{task_text}

Return only the structured result requested by the Claude CLI schema:
- `status` and `finalResult` must match and use DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, BLOCKED, or FAIL.
- `role` must be `{role}`.
- Include concise `summary`, `changedFiles`, `verification`, `findings`, and `risksOrFollowUps`.
- `verification` must name actual commands and outcomes; use an empty list only when the status explains why verification could not run.
"""
