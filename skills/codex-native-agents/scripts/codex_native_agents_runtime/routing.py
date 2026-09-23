from __future__ import annotations

from dataclasses import dataclass

from .contract import load_contract
from .common import ContractError


@dataclass(frozen=True)
class ModelRoute:
    profile: str
    model: str | None
    reasoning_effort: str | None
    fallback: str | None = None


def route_for_task(
    role: str,
    complexity: str = "normal",
    available_models: set[str] | None = None,
) -> ModelRoute:
    if complexity not in {"simple", "normal", "complex", "high-risk"}:
        raise ContractError("Unsupported complexity")
    contract = load_contract()
    profile = contract["roleProfiles"][role]
    if role == "researcher" and complexity == "complex":
        profile = "balanced"
    if role == "implementer" and complexity in {"complex", "high-risk"}:
        profile = "balancedHigh"
    if role in {"planner", "reviewer"} and complexity == "normal":
        profile = "balancedHigh"
    if role == "final-verifier" or complexity == "high-risk":
        profile = "frontier"

    selected = contract["modelProfiles"][profile]
    model = selected["model"]
    if available_models is not None and model not in available_models:
        return ModelRoute(profile, None, None, contract["spawn"]["fallbackPolicy"])
    return ModelRoute(profile, model, selected["reasoningEffort"])
