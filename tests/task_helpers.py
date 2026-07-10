from __future__ import annotations


def compliant_task(text: str, verification: str = "dry-run artifact generation completed") -> str:
    return f"""# Delegated Task

Goal
{text}

Allowed Scope
- skills/codex-with-cc

Forbidden Actions
- Do not edit README.md.
- Do not invoke nested delegate runs.

Acceptance Criteria
- The task stays inside the assigned scope.
- The worker report contains concrete verification evidence.

Verification
- {verification}

Report Requirements
- Status / Role / Summary / Changed Files / Verification / Findings / Final Result / Risks Or Follow-ups
"""


def compliant_native_task(text: str = "Inspect the native runtime contract.") -> str:
    return f"""# Native Codex Agent Task

Goal
{text}

Allowed Scope
- skills/codex-native-agents

Forbidden Actions
- Do not edit README.md.
- Do not invoke nested delegate runs.

Acceptance Criteria
- The task stays inside the assigned scope.
- The worker report contains concrete verification evidence.

Verification
- PYTHONNOUSERSITE=1 python3 -m pytest tests/test_native_runtime.py -q

Report Requirements
- Status / Role / Summary / Changed Files / Verification / Findings / Final Result / Risks Or Follow-ups
"""


def compliant_native_report(
    status: str = "DONE", role: str = "researcher"
) -> str:
    return f"""Status
{status}

Role
{role}

Summary
- Native runtime validation completed.

Changed Files
- None

Verification
- PYTHONNOUSERSITE=1 python3 -m pytest tests/test_native_runtime.py -q

Findings
- None

Final Result
{status}

Risks Or Follow-ups
- None
"""
