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
    reason: str = ""
    preferred_profile: str | None = None


# This order expresses routing policy; JSON object order has no routing meaning.
# Only exact configured model IDs and advertised reasoning efforts are eligible.
_AUTOMATIC_CANDIDATES = {
    "economy": ("economy", "balanced61", "balancedHigh61", "deliberate61", "frontier"),
    "balanced61": ("balanced61", "balancedHigh61", "deliberate61", "frontier"),
    "balancedHigh61": ("balancedHigh61", "deliberate61", "frontier"),
    "deliberate61": ("deliberate61", "frontier"),
    # Preserve registered pre-6.1 routes and explicit legacy pins.
    "balanced": ("balanced", "balancedHigh", "frontier"),
    "balancedHigh": ("balancedHigh", "frontier"),
    "frontier": ("frontier",),
}
_ESCALATION_CANDIDATES = {
    "economy": ("balanced61", "balancedHigh61", "deliberate61", "frontier"),
    "balanced61": ("frontier",),
    "balancedHigh61": ("frontier",),
    "deliberate61": ("frontier",),
    "balanced": ("frontier",),
    "balancedHigh": ("frontier",),
    "frontier": (),
}


def _select_route(
    preferred_profile: str,
    candidates: tuple[str, ...],
    *,
    capabilities: dict[str, list[str]] | None,
    available_models: set[str] | None = None,
    reason: str,
) -> ModelRoute:
    contract = load_contract()
    unavailable = []
    for profile in candidates:
        selected = contract["modelProfiles"][profile]
        model = selected["model"]
        effort = selected["reasoningEffort"]
        if available_models is not None and model not in available_models:
            unavailable.append(f"{profile}: {model} not available")
            continue
        if capabilities is not None:
            if model not in capabilities:
                unavailable.append(f"{profile}: {model} not advertised by host")
                continue
            if effort not in capabilities[model]:
                unavailable.append(f"{profile}: {model} does not advertise {effort} effort")
                continue
        details = f"{reason}; selected {profile} ({model}, {effort})"
        if unavailable:
            details += "; skipped " + "; ".join(unavailable)
        return ModelRoute(
            profile, model, effort, reason=details, preferred_profile=preferred_profile
        )
    details = f"{reason}; no eligible model/effort pair; return to main thread"
    if unavailable:
        details += "; " + "; ".join(unavailable)
    return ModelRoute(
        preferred_profile,
        None,
        None,
        contract["spawn"]["fallbackPolicy"],
        details,
        preferred_profile,
    )


def route_for_task(
    role: str,
    complexity: str = "normal",
    available_models: set[str] | None = None,
    *,
    capabilities: dict[str, list[str]] | None = None,
    model_profile: str | None = None,
    risk: str = "normal",
) -> ModelRoute:
    if complexity not in {"simple", "normal", "complex", "high-risk"}:
        raise ContractError("Unsupported complexity")
    if risk not in {"normal", "high"}:
        raise ContractError("Unsupported risk")
    high_risk = risk == "high" or complexity == "high-risk"
    contract = load_contract()
    if role not in contract["roleProfiles"]:
        raise ContractError(f"Unsupported worker role: {role}")
    profile = contract["roleProfiles"][role]
    if role == "researcher" and complexity == "simple":
        profile = "economy"
    if role == "reviewer" and complexity == "simple":
        profile = "balanced61"
    if role in {"implementer", "researcher"} and complexity == "complex":
        profile = "balancedHigh61"
    if role in {"planner", "reviewer"} and complexity == "complex":
        profile = "deliberate61"
    if role == "final-verifier" or high_risk:
        profile = "frontier"
    reason = f"{role}/{complexity} risk={'high' if high_risk else 'normal'} prefers {profile}"
    if model_profile is not None:
        if model_profile not in _AUTOMATIC_CANDIDATES:
            raise ContractError(f"Unsupported model profile: {model_profile}")
        if (
            role == "final-verifier" or high_risk
        ) and model_profile != "frontier":
            raise ContractError(
                "High-risk tasks and final verification require frontier; "
                "model override cannot downgrade"
            )
        profile = model_profile
        candidates = (profile,)
        reason += f"; explicitly pinned to {profile}, automatic substitution disabled"
    else:
        candidates = _AUTOMATIC_CANDIDATES[profile]
    return _select_route(
        profile,
        candidates,
        capabilities=capabilities,
        available_models=available_models,
        reason=reason,
    )


def escalate_route(
    profile: str,
    capabilities: dict[str, list[str]] | None = None,
) -> ModelRoute:
    """Select one stronger retry route; the workflow enforces the retry limit."""
    if profile not in _ESCALATION_CANDIDATES:
        raise ContractError(f"Unsupported model profile: {profile}")
    candidates = _ESCALATION_CANDIDATES[profile]
    preferred = candidates[0] if candidates else profile
    return _select_route(
        preferred,
        candidates,
        capabilities=capabilities,
        reason=f"Failure escalation from {profile}",
    )
