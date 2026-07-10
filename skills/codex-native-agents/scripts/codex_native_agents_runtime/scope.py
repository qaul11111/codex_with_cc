from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Iterable

from .common import ContractError


WINDOWS_DRIVE_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")


def normalize_scopes(values: Iterable[str]) -> tuple[str, ...]:
    normalized: set[str] = set()
    for value in values:
        scope = value.strip()
        if not scope:
            continue
        path = PurePosixPath(scope)
        if (
            "\\" in scope
            or WINDOWS_DRIVE_ABSOLUTE.match(scope)
            or path.is_absolute()
            or ".." in path.parts
        ):
            raise ContractError("Scopes must be non-empty project-relative paths")
        normalized.add(path.as_posix().strip("/"))
    if not normalized or "." in normalized:
        raise ContractError("Scopes must be non-empty project-relative paths")
    return tuple(sorted(normalized))


def scopes_overlap(left: Iterable[str], right: Iterable[str]) -> bool:
    left_scopes = normalize_scopes(left)
    right_scopes = normalize_scopes(right)
    return any(
        first == second
        or first.startswith(second + "/")
        or second.startswith(first + "/")
        for first in left_scopes
        for second in right_scopes
    )
