from __future__ import annotations

from dataclasses import dataclass

from .common import ContractError
from .contract import load_contract


@dataclass(frozen=True)
class WorkerReport:
    status: str
    role: str
    final_result: str
    sections: dict[str, str]


def extract_report_sections(text: str) -> dict[str, str]:
    headings = load_contract()["reportHeadings"]
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        heading = line.strip().lstrip("#").strip().rstrip(":")
        if heading in headings:
            current = heading
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def parse_worker_report(text: str) -> WorkerReport:
    contract = load_contract()
    sections = extract_report_sections(text)
    missing = [name for name in contract["reportHeadings"] if not sections.get(name)]
    if missing:
        raise ContractError("Missing or empty report sections: " + ", ".join(missing))

    status = sections["Status"].splitlines()[0].strip()
    role = sections["Role"].splitlines()[0].strip()
    final_result = sections["Final Result"].splitlines()[0].strip()
    if status not in contract["reportStatusValues"] or final_result != status:
        raise ContractError("Status and Final Result must use the same valid token")
    if role not in contract["workerRoles"]:
        raise ContractError(f"Unsupported report role: {role}")
    return WorkerReport(status, role, final_result, sections)
