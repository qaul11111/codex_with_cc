from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def repo() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def contract(repo: Path) -> dict[str, object]:
    return json.loads(
        (repo / "skills/codex-native-agents/contract.json").read_text(encoding="utf-8")
    )


def test_model_profiles_are_soft_policy(contract: dict[str, object]) -> None:
    spawn = contract["spawn"]
    model_profiles = contract["modelProfiles"]

    assert isinstance(spawn, dict)
    assert isinstance(model_profiles, dict)
    assert spawn["forkContext"] is False
    assert spawn["fallbackPolicy"] == "inherit_parent"
    assert model_profiles["economy"] == {
        "model": "gpt-5.6-luna", "reasoningEffort": "medium"
    }
    assert model_profiles["balanced"] == {
        "model": "gpt-5.6-terra", "reasoningEffort": "medium"
    }
    assert model_profiles["frontier"] == {
        "model": "gpt-5.6-sol", "reasoningEffort": "high"
    }


def test_native_contract_retains_the_approved_shared_fields(contract: dict[str, object]) -> None:
    assert contract["schemaVersion"] == 1
    assert contract["invocationContract"] == "codex_native_agents_workflow"
    assert contract["artifactSchemaVersion"] == 1
    assert contract["spawn"] == {
        "forkContext": False,
        "fallbackPolicy": "inherit_parent",
        "maxEscalations": 1,
    }
    assert contract["modelProfiles"]["balancedHigh"] == {
        "model": "gpt-5.6-terra", "reasoningEffort": "high"
    }
    assert contract["roleProfiles"] == {
        "planner": "balancedHigh",
        "implementer": "balanced",
        "researcher": "economy",
        "reviewer": "balancedHigh",
        "final-verifier": "frontier",
    }
    assert contract["workerRoles"] == [
        "planner",
        "implementer",
        "researcher",
        "reviewer",
        "final-verifier",
    ]
    assert contract["reportStatusValues"] == [
        "DONE",
        "DONE_WITH_CONCERNS",
        "NEEDS_CONTEXT",
        "BLOCKED",
        "FAIL",
    ]
    assert contract["reportHeadings"] == [
        "Status",
        "Role",
        "Summary",
        "Changed Files",
        "Verification",
        "Findings",
        "Final Result",
        "Risks Or Follow-ups",
    ]
    assert contract["reviewKinds"] == ["spec", "quality"]
    assert contract["taskFile"]["requiredSections"] == [
        "Goal",
        "Allowed Scope",
        "Forbidden Actions",
        "Acceptance Criteria",
        "Verification",
        "Report Requirements",
    ]
    assert contract["triggerPatterns"] == [
        "child[- ]?agent",
        "sub[- ]?agent",
        "child[- ]?thread",
        "sub[- ]?thread",
        "delegat(?:e|ion|ing)",
        "worker[- ]?execution",
        "子代理|子线程|多代理|委派|派工|执行层",
    ]


def test_core_skill_requires_native_task_envelope_and_main_thread_dispatch(repo: Path) -> None:
    skill = (repo / "skills/codex-native-agents/SKILL.md").read_text(encoding="utf-8")
    human_contract = (repo / "skills/codex-native-agents/CODEX_NATIVE_AGENTS.md").read_text(
        encoding="utf-8"
    )

    envelope = """[NATIVE_CODEX_AGENT_TASK]
WorkflowId: native-auth-workflow
TaskId: auth-token-implementation
Role: implementer
TaskFile: .codex/codex_native_agents/tasks/auth-token-implementation.md
Scope: src/auth,tests/auth
ModelProfile: balanced
Writable: true
Parallel: false
DispatcherRole: main
[/NATIVE_CODEX_AGENT_TASK]"""

    assert envelope in skill
    assert "main thread owns dispatch" in skill
    assert "cannot call `spawn_agent` recursively" in skill
    assert "main thread owns dispatch" in human_contract
    assert "cannot call `spawn_agent` recursively" in human_contract


def test_contract_documents_host_tool_isolation_provenance_boundary(
    repo: Path, contract: dict[str, object]
) -> None:
    provenance = contract["provenance"]
    skill = (repo / "skills/codex-native-agents/SKILL.md").read_text(encoding="utf-8")
    human_contract = (repo / "skills/codex-native-agents/CODEX_NATIVE_AGENTS.md").read_text(
        encoding="utf-8"
    )

    assert provenance == {
        "hostTranscriptFields": ["transcript_path", "transcriptPath"],
        "subagentSessionMetaSignals": [
            "source.subagent",
            "thread_source=subagent",
            "parent_thread_id",
        ],
        "fallbackPolicy": "host_tool_isolation",
    }
    assert "host tool isolation" in skill
    assert "host tool isolation" in human_contract
