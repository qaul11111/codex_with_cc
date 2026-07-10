from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
CLI = "skills/codex-native-agents/scripts/native_agents.py"


def test_local_installation_documents_the_supported_development_flow() -> None:
    install = (REPO / "AI_INSTALL.md").read_text(encoding="utf-8")

    assert "https://github.com/qaul11111/codex_with_cc" in install
    assert "create_basic_plugin.py codex-native-agents --with-marketplace" in install
    assert "update_plugin_cachebuster.py" in install
    assert "read_marketplace_name.py" in install
    assert "codex plugin add codex-native-agents@personal" in install
    assert "Do not hand-edit" in install


def test_stage_skills_document_the_native_cli_evidence_flow() -> None:
    dispatching = (REPO / "skills/codex-native-agents-dispatching/SKILL.md").read_text(encoding="utf-8")
    reviewing = (REPO / "skills/codex-native-agents-reviewing/SKILL.md").read_text(encoding="utf-8")
    finishing = (REPO / "skills/codex-native-agents-finishing/SKILL.md").read_text(encoding="utf-8")

    for command in ("init", "validate-task", "register-task", "record-spawn", "record-run", "verify"):
        assert f"{CLI} {command}" in dispatching
    assert "--review-for-task-id" in dispatching
    assert "--review-kind" in dispatching
    assert "--model-profile" in dispatching
    assert "--writable" in dispatching
    assert "--parallel" in dispatching
    assert "record-run" in reviewing
    assert "record-run" in finishing
