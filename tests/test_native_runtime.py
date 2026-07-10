from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.task_helpers import compliant_native_report, compliant_native_task


REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "skills" / "codex-native-agents" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from codex_native_agents_runtime.common import ContractError
from codex_native_agents_runtime.reports import parse_worker_report
from codex_native_agents_runtime.routing import route_for_task
from codex_native_agents_runtime.scope import normalize_scopes, scopes_overlap
from codex_native_agents_runtime.task_contract import validate_task_file


def test_route_for_task_uses_role_and_risk() -> None:
    assert route_for_task("researcher", "normal").profile == "economy"
    assert route_for_task("implementer", "normal").profile == "balanced"
    assert route_for_task("implementer", "complex").profile == "balancedHigh"
    assert route_for_task("final-verifier", "high-risk").profile == "frontier"


def test_unavailable_model_falls_back_to_parent() -> None:
    route = route_for_task("researcher", "normal", available_models={"gpt-5.6-terra"})

    assert route.model is None
    assert route.reasoning_effort is None
    assert route.fallback == "inherit_parent"


def test_parallel_writable_scopes_must_not_overlap() -> None:
    assert scopes_overlap(["src/auth"], ["src/auth/token.py"])
    assert not scopes_overlap(["src/auth"], ["src/billing"])


@pytest.mark.parametrize(
    "scope",
    [
        "../src",
        "src/../secrets",
        r"src\..\secrets",
        r"..\secrets",
        r"C:\secrets",
    ],
)
def test_normalize_scopes_rejects_parent_traversal(scope: str) -> None:
    with pytest.raises(ContractError, match="project-relative"):
        normalize_scopes([scope])


def test_validate_task_file_accepts_contract_aliases(tmp_path: Path) -> None:
    task_file = tmp_path / "task.md"
    task_file.write_text(
        compliant_native_task()
        .replace("Goal", "Assignment", 1)
        .replace("Allowed Scope", "Allowed Files", 1)
        .replace("Forbidden Actions", "Out of Scope", 1)
        .replace("Acceptance Criteria", "Self Check", 1)
        .replace("Verification", "Required Verification", 1)
        .replace("Report Requirements", "Worker Report", 1),
        encoding="utf-8",
    )

    sections = validate_task_file(task_file, "implementer")

    assert sections["Goal"] == "Inspect the native runtime contract."
    assert sections["Allowed Scope"] == "- skills/codex-native-agents"


def test_validate_task_file_rejects_empty_required_section(tmp_path: Path) -> None:
    task_file = tmp_path / "task.md"
    task_file.write_text(
        compliant_native_task().replace(
            "- Do not edit README.md.\n- Do not invoke nested delegate runs.", ""
        ),
        encoding="utf-8",
    )

    with pytest.raises(ContractError, match="Missing or empty task sections: Forbidden Actions"):
        validate_task_file(task_file, "researcher")


def test_validate_task_file_rejects_unknown_role(tmp_path: Path) -> None:
    task_file = tmp_path / "task.md"
    task_file.write_text(compliant_native_task(), encoding="utf-8")

    with pytest.raises(ContractError, match="Unsupported worker role: operator"):
        validate_task_file(task_file, "operator")


def test_parse_worker_report_returns_validated_report() -> None:
    report = parse_worker_report(compliant_native_report("DONE_WITH_CONCERNS", "reviewer"))

    assert report.status == "DONE_WITH_CONCERNS"
    assert report.role == "reviewer"
    assert report.final_result == "DONE_WITH_CONCERNS"
    assert report.sections["Summary"] == "- Native runtime validation completed."


@pytest.mark.parametrize(
    ("report", "message"),
    [
        (compliant_native_report().replace("Findings\n- None\n\n", ""), "Findings"),
        (compliant_native_report(role="operator"), "Unsupported report role: operator"),
        (compliant_native_report(status="PENDING"), "same valid token"),
        (
            compliant_native_report().replace("Final Result\nDONE", "Final Result\nFAIL"),
            "same valid token",
        ),
    ],
)
def test_parse_worker_report_rejects_contract_violations(report: str, message: str) -> None:
    with pytest.raises(ContractError, match=message):
        parse_worker_report(report)
