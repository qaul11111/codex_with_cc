from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def clear_inherited_codex_thread_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
