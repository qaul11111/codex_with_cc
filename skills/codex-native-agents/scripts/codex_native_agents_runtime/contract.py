from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=1)
def load_contract() -> dict[str, Any]:
    contract_path = Path(__file__).resolve().parents[2] / "contract.json"
    with contract_path.open(encoding="utf-8") as contract_file:
        return json.load(contract_file)
