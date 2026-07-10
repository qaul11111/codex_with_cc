from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


@pytest.fixture
def repo() -> Path:
    return Path(__file__).resolve().parents[1]


def test_native_plugin_manifest(repo: Path) -> None:
    manifest = json.loads((repo / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))

    assert manifest["name"] == "codex-native-agents"
    assert re.fullmatch(r"0\.1\.0(?:\+codex\.[A-Za-z0-9.-]+)?", manifest["version"])
    assert manifest["repository"] == "https://github.com/qaul11111/codex_with_cc"
    assert "legacy-delegation" not in json.dumps(manifest)
    assert "hooks" not in manifest
    assert (repo / "hooks/hooks.json").exists()
