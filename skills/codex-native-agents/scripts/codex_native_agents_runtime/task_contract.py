from __future__ import annotations

from pathlib import Path

from .common import ContractError
from .contract import load_contract


def split_sections(text: str) -> dict[str, str]:
    aliases = load_contract()["taskFile"]["sectionAliases"]
    alias_to_name = {
        alias.lower(): name
        for name, values in aliases.items()
        for alias in values
    }
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        heading = line.strip().lstrip("#").strip().rstrip(":").lower()
        if heading in alias_to_name:
            current = alias_to_name[heading]
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def validate_task_file(path: Path, role: str) -> dict[str, str]:
    contract = load_contract()
    if role not in contract["workerRoles"]:
        raise ContractError(f"Unsupported worker role: {role}")
    sections = split_sections(path.read_text(encoding="utf-8"))
    missing = [
        name
        for name in contract["taskFile"]["requiredSections"]
        if not sections.get(name)
    ]
    if missing:
        raise ContractError("Missing or empty task sections: " + ", ".join(missing))
    return sections
