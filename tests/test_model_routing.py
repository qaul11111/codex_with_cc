"""Routing policy tests use advertised capabilities; no models are invoked."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "skills/codex-native-agents/scripts")
)

from codex_native_agents_runtime.common import ContractError
from codex_native_agents_runtime.contract import load_contract
from codex_native_agents_runtime.routing import escalate_route, route_for_task


FULL_CAPABILITIES = {
    "gpt-6-luna": ["low", "medium", "high", "xhigh"],
    "gpt-6-sol": ["low", "medium", "high", "xhigh"],
    "gpt-6-astra": ["low", "medium", "high", "xhigh"],
}
PROFILE_PAIRS = {
    "economy": ("gpt-6-luna", "low"),
    "balanced": ("gpt-6-sol", "medium"),
    "balancedHigh": ("gpt-6-sol", "high"),
    "frontier": ("gpt-6-astra", "xhigh"),
}


@pytest.mark.parametrize(
    "role,complexity,expected",
    [
        ("researcher", "simple", "economy"),
        ("researcher", "normal", "balanced"),
        ("researcher", "complex", "balancedHigh"),
        ("researcher", "high-risk", "frontier"),
        ("implementer", "simple", "balanced"),
        ("implementer", "normal", "balanced"),
        ("implementer", "complex", "balancedHigh"),
        ("implementer", "high-risk", "frontier"),
        ("planner", "simple", "balanced"),
        ("planner", "normal", "balanced"),
        ("planner", "complex", "frontier"),
        ("planner", "high-risk", "frontier"),
        ("reviewer", "simple", "balanced"),
        ("reviewer", "normal", "balancedHigh"),
        ("reviewer", "complex", "frontier"),
        ("reviewer", "high-risk", "frontier"),
        ("final-verifier", "simple", "frontier"),
        ("final-verifier", "normal", "frontier"),
        ("final-verifier", "complex", "frontier"),
        ("final-verifier", "high-risk", "frontier"),
    ],
)
def test_role_and_complexity_choose_a_model_and_effort(role, complexity, expected):
    route = route_for_task(role, complexity, capabilities=FULL_CAPABILITIES)

    assert route.profile == route.preferred_profile == expected
    assert (route.model, route.reasoning_effort) == PROFILE_PAIRS[expected]
    assert route.fallback is None
    assert f"{role}/{complexity}" in route.reason


@pytest.mark.parametrize(
    "capabilities,expected",
    [
        ({"gpt-6-sol": ["medium", "high"]}, "balanced"),
        ({"gpt-6-sol": ["high"]}, "balancedHigh"),
        ({"gpt-6-astra": ["xhigh"]}, "frontier"),
    ],
)
def test_unavailable_economy_moves_only_upward(capabilities, expected):
    route = route_for_task("researcher", "simple", capabilities=capabilities)

    assert route.profile == expected
    assert route.preferred_profile == "economy"
    assert (route.model, route.reasoning_effort) == PROFILE_PAIRS[expected]
    assert "gpt-6-luna not advertised" in route.reason


def test_unavailable_effort_uses_next_supported_profile_without_inventing_effort():
    route = route_for_task(
        "implementer", capabilities={"gpt-6-sol": ["low", "high"]}
    )

    assert route.profile == "balancedHigh"
    assert route.reasoning_effort == "high"
    assert route.preferred_profile == "balanced"
    assert "does not advertise medium effort" in route.reason


@pytest.mark.parametrize(
    "role,complexity,capabilities",
    [
        ("implementer", "complex", {"gpt-6-sol": ["medium"]}),
        ("implementer", "normal", {"gpt-6-luna": ["low"]}),
        ("planner", "high-risk", {"gpt-6-sol": ["high"]}),
        ("reviewer", "complex", {"gpt-6-sol": ["high"]}),
        ("final-verifier", "simple", {"gpt-6-astra": ["high"]}),
        ("researcher", "simple", {}),
    ],
)
def test_no_available_stronger_pair_returns_to_main(role, complexity, capabilities):
    route = route_for_task(role, complexity, capabilities=capabilities)

    assert route.fallback == "main_thread"
    assert route.model is route.reasoning_effort is None
    assert "return to main thread" in route.reason


def test_candidate_order_does_not_depend_on_contract_or_host_dictionary_order(monkeypatch):
    contract = {**load_contract()}
    contract["modelProfiles"] = dict(reversed(list(contract["modelProfiles"].items())))
    monkeypatch.setattr("codex_native_agents_runtime.routing.load_contract", lambda: contract)
    host = {"gpt-6-astra": ["xhigh"], "gpt-6-sol": ["high", "medium"]}

    route = route_for_task("researcher", "simple", capabilities=host)

    assert (route.model, route.reasoning_effort) == ("gpt-6-sol", "medium")


def test_model_allowlist_and_capability_efforts_both_constrain_selection():
    route = route_for_task(
        "researcher",
        "simple",
        available_models={"gpt-6-sol"},
        capabilities=FULL_CAPABILITIES,
    )

    assert route.profile == "balanced"
    assert route.preferred_profile == "economy"


@pytest.mark.parametrize(
    "legacy_models",
    [
        {"gpt-5.6-luna": ["low"], "gpt-5.6-sol": ["medium", "high"]},
        {"gpt-6-luna-latest": ["low"], "gpt-6-sol-latest": ["medium"]},
        {"luna": ["low"], "sol": ["medium"], "astra": ["xhigh"]},
    ],
)
def test_model_aliases_and_older_versions_are_not_gpt6_capabilities(legacy_models):
    route = route_for_task("researcher", "simple", capabilities=legacy_models)

    assert route.fallback == "main_thread"
    assert route.model is None


def test_actual_host_with_older_sol_luna_only_uses_advertised_gpt6_astra():
    route = route_for_task(
        "researcher",
        "simple",
        capabilities={
            "gpt-5.6-luna": ["low"],
            "gpt-5.6-sol": ["medium", "high"],
            "gpt-6-astra": ["low", "medium", "high", "xhigh"],
        },
    )

    assert route.profile == "frontier"
    assert route.model == "gpt-6-astra"
    assert route.reasoning_effort == "xhigh"


def test_explicit_profile_is_used_when_available():
    route = route_for_task(
        "implementer", capabilities=FULL_CAPABILITIES, model_profile="economy"
    )

    assert route.profile == route.preferred_profile == "economy"
    assert route.model == "gpt-6-luna"
    assert "explicitly pinned" in route.reason


def test_unavailable_explicit_profile_does_not_substitute_even_a_stronger_model():
    route = route_for_task(
        "implementer",
        capabilities={"gpt-6-astra": ["xhigh"]},
        model_profile="balanced",
    )

    assert route.profile == route.preferred_profile == "balanced"
    assert route.fallback == "main_thread"
    assert route.model is None


@pytest.mark.parametrize("profile", ["economy", "balanced", "balancedHigh"])
@pytest.mark.parametrize(
    "role,complexity",
    [("implementer", "high-risk"), ("final-verifier", "simple")],
)
def test_explicit_profile_cannot_lower_required_frontier(role, complexity, profile):
    with pytest.raises(ContractError, match="require frontier"):
        route_for_task(
            role, complexity, capabilities=FULL_CAPABILITIES, model_profile=profile
        )


@pytest.mark.parametrize(
    "profile,expected",
    [("economy", "balanced"), ("balanced", "frontier"), ("balancedHigh", "frontier")],
)
def test_failure_escalation_changes_model_tier(profile, expected):
    route = escalate_route(profile, FULL_CAPABILITIES)

    assert route.profile == route.preferred_profile == expected
    assert (route.model, route.reasoning_effort) == PROFILE_PAIRS[expected]
    assert f"from {profile}" in route.reason


def test_failure_escalation_checks_supported_effort_and_skips_missing_sol():
    route = escalate_route("economy", {"gpt-6-astra": ["xhigh"]})

    assert route.profile == "frontier"
    assert route.preferred_profile == "balanced"
    assert "gpt-6-sol not advertised" in route.reason


def test_failure_escalation_can_select_supported_sol_high_when_medium_is_missing():
    route = escalate_route("economy", {"gpt-6-sol": ["high"]})

    assert route.profile == "balancedHigh"
    assert route.reasoning_effort == "high"


@pytest.mark.parametrize("profile", ["balanced", "balancedHigh", "frontier"])
def test_failure_escalation_never_retries_same_tier_or_downgrades(profile):
    route = escalate_route(profile, {"gpt-6-sol": ["medium", "high"]})

    assert route.fallback == "main_thread"
    assert route.model is None


def test_frontier_failure_returns_to_main_even_with_full_capabilities():
    route = escalate_route("frontier", FULL_CAPABILITIES)

    assert route.profile == "frontier"
    assert route.fallback == "main_thread"
    assert route.model is route.reasoning_effort is None


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"role": "operator"}, "Unsupported worker role"),
        ({"role": "researcher", "complexity": "unknown"}, "Unsupported complexity"),
        ({"role": "researcher", "model_profile": "cheap"}, "Unsupported model profile"),
    ],
)
def test_invalid_routing_inputs_fail_explicitly(kwargs, message):
    with pytest.raises(ContractError, match=message):
        route_for_task(**kwargs)


def test_invalid_escalation_profile_fails_explicitly():
    with pytest.raises(ContractError, match="Unsupported model profile"):
        escalate_route("cheap", FULL_CAPABILITIES)
