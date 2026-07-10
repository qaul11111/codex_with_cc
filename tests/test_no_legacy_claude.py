from __future__ import annotations

from pathlib import Path


FORBIDDEN_RUNTIME_TOKENS = (
    "delegate_to_claude",
    "CODEX_CLAUDE_CHILD_THREAD",
    "claude_cli.py",
    "thinking_strip_proxy",
    "openai_compatible_report",
    "PrimaryReuse",
    "PrimaryAnchor",
    "ParallelPool",
)

ACTIVE_SURFACES = (
    ".codex-plugin",
    "AI_INSTALL.md",
    "README.md",
    "blog",
    "docs",
    "examples",
    "hooks",
    "scripts",
    "skills",
    "tests",
)

HISTORICAL_DOCS = (
    Path("docs/superpowers/plans"),
    Path("docs/superpowers/specs"),
    Path("docs/MIGRATION.md"),
)


def scan_runtime_and_docs(repo: Path) -> str:
    excluded = {repo / "tests" / "test_no_legacy_claude.py"}
    excluded.update(repo / path for path in HISTORICAL_DOCS)
    contents: list[str] = []

    for surface in ACTIVE_SURFACES:
        path = repo / surface
        if path.is_file():
            paths = (path,)
        elif path.is_dir():
            paths = (candidate for candidate in path.rglob("*") if candidate.is_file())
        else:
            continue
        for candidate in paths:
            if (
                "__pycache__" in candidate.parts
                or candidate in excluded
                or any(parent in excluded for parent in candidate.parents)
            ):
                continue
            contents.append(candidate.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(contents)


def test_no_legacy_runtime_paths_remain() -> None:
    repo = Path(__file__).resolve().parents[1]
    scanned = scan_runtime_and_docs(repo)
    for token in FORBIDDEN_RUNTIME_TOKENS:
        assert token not in scanned
