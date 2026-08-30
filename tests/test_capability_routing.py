"""Tests for deterministic phase-capability instrument binding."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from marianne_compiler.capabilities import (
    CapabilityResolutionError,
    bind_config_to_capabilities,
    bind_score_to_capabilities,
    resolve_phase_routes,
)

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def _profile(
    name: str,
    *,
    provider: str,
    model: str,
    capabilities: list[str],
    priority: int = 100,
    reliability_class: str = "standard",
    metered_cost: str = "paid",
    context_tokens: int = 200_000,
) -> dict[str, object]:
    return {
        "name": name,
        "available": True,
        "provider": provider,
        "model": model,
        "capabilities": capabilities,
        "priority": priority,
        "reliability_class": reliability_class,
        "metered_cost": metered_cost,
        "latency_class": "normal",
        "context_tokens": context_tokens,
        "verified_at": "2026-08-30T11:30:00Z",
        "invocation_contract_verified": True,
        "entitlement_verified": True,
    }


def test_resolver_rejects_dj_profile_and_misrouted_glm() -> None:
    inventory = {
        "profiles": [
            _profile(
                "musician-0042",
                provider="z.ai",
                model="zai-coding-plan/glm-5.3-flash",
                capabilities=["file_editing", "vision"],
                priority=1,
            ),
            _profile(
                "musician-ember",
                provider="z.ai",
                model="zai-coding-plan/glm-5.3-flash",
                capabilities=["file_editing", "vision"],
                priority=1,
            ),
            _profile(
                "openrouter-ox-alpha",
                provider="openrouter",
                model="glm-5.3-flash",
                capabilities=["file_editing", "vision"],
                priority=2,
                metered_cost="free",
            ),
            _profile(
                "zai-live",
                provider="z.ai",
                model="zai-coding-plan/glm-5.3-flash",
                capabilities=["file_editing", "vision"],
                priority=10,
                metered_cost="subscription",
                context_tokens=1_000_000,
            ),
            _profile(
                "codex-cli",
                provider="openai",
                model="gpt-5.6-codex",
                capabilities=["file_editing", "vision"],
                priority=20,
            ),
        ]
    }

    result = resolve_phase_routes(
        "work",
        {
            "required_capabilities": ["file_editing", "vision"],
            "min_context_tokens": 150_000,
            "max_fallbacks": 2,
            "load_bearing": True,
        },
        inventory,
        now=NOW,
    )

    assert [item["name"] for item in result["selected"]] == ["zai-live", "codex-cli"]
    rejected = {item["name"]: item["reasons"] for item in result["rejected"]}
    assert "dj_project_profile_forbidden" in rejected["musician-0042"]
    assert "dj_project_profile_forbidden" in rejected["musician-ember"]
    assert "glm_5_3_flash_requires_zai" in rejected["openrouter-ox-alpha"]


def test_supplementary_zero_metered_lane_is_not_load_bearing_primary() -> None:
    inventory = {
        "profiles": [
            _profile(
                "queued-free",
                provider="example",
                model="free-model",
                capabilities=["file_editing"],
                priority=1,
                reliability_class="supplementary",
                metered_cost="zero",
            ),
            _profile(
                "reliable-paid",
                provider="example",
                model="paid-model",
                capabilities=["file_editing"],
                priority=50,
                reliability_class="standard",
            ),
        ]
    }

    result = resolve_phase_routes(
        "work",
        {"required_capabilities": ["file_editing"], "load_bearing": True},
        inventory,
        now=NOW,
    )

    assert result["selected"][0]["name"] == "reliable-paid"
    assert result["selected"][1]["name"] == "queued-free"
    assert "supplementary_lane_not_primary" in result["selected"][1]["notes"]


def test_load_bearing_phase_fails_when_only_supplementary_route_exists() -> None:
    inventory = {
        "profiles": [
            _profile(
                "queued-free",
                provider="example",
                model="free-model",
                capabilities=["file_editing"],
                reliability_class="supplementary",
                metered_cost="zero",
            )
        ]
    }

    with pytest.raises(CapabilityResolutionError, match="load-bearing"):
        resolve_phase_routes(
            "work",
            {"required_capabilities": ["file_editing"], "load_bearing": True},
            inventory,
            now=NOW,
        )


@pytest.mark.parametrize("reliability", ["supplementary ", "unknown"])
def test_load_bearing_phase_rejects_malformed_reliability_classes(
    reliability: str,
) -> None:
    inventory = {
        "profiles": [
            _profile(
                "ambiguous",
                provider="example",
                model="model",
                capabilities=["file_editing"],
                reliability_class=reliability,
            )
        ]
    }

    with pytest.raises(CapabilityResolutionError, match="No live instrument"):
        resolve_phase_routes(
            "work",
            {"required_capabilities": ["file_editing"], "load_bearing": True},
            inventory,
            now=NOW,
        )


def test_binding_refuses_capability_route_for_deterministic_cli_phase() -> None:
    config = {
        "defaults": {
            "phase_requirements": {
                "temperature_check": {"required_capabilities": ["shell_access"]}
            }
        },
        "agents": [
            {
                "name": "canyon",
                "instruments": {"cli": {"primary": {"instrument": "stale"}}},
            }
        ],
    }

    with pytest.raises(CapabilityResolutionError, match="deterministic CLI phase"):
        bind_config_to_capabilities(config, {"profiles": []}, now=NOW)


def test_resolution_is_deterministic_across_inventory_order() -> None:
    profiles = [
        _profile(
            "bravo",
            provider="example",
            model="b",
            capabilities=["structured_output"],
            priority=20,
        ),
        _profile(
            "alpha",
            provider="example",
            model="a",
            capabilities=["structured_output"],
            priority=20,
        ),
    ]
    requirements = {"required_capabilities": ["structured_output"]}

    first = resolve_phase_routes(
        "inspect", requirements, {"profiles": profiles}, now=NOW
    )
    second = resolve_phase_routes(
        "inspect", requirements, {"profiles": list(reversed(profiles))}, now=NOW
    )

    assert first == second
    assert [item["name"] for item in first["selected"]] == ["alpha", "bravo"]


def test_binding_materializes_primary_fallbacks_and_receipt() -> None:
    config = {
        "defaults": {
            "phase_requirements": {
                "work": {
                    "required_capabilities": ["file_editing"],
                    "load_bearing": True,
                },
                "inspect": {"required_capabilities": ["vision"]},
            }
        },
        "agents": [{"name": "canyon", "voice": "v", "focus": "f"}],
    }
    inventory = {
        "profiles": [
            _profile(
                "zai-live",
                provider="z.ai",
                model="zai-coding-plan/glm-5.3-flash",
                capabilities=["file_editing", "vision"],
                priority=10,
            ),
            _profile(
                "codex-cli",
                provider="openai",
                model="gpt-5.6-codex",
                capabilities=["file_editing", "vision"],
                priority=20,
            ),
        ]
    }

    bound = bind_config_to_capabilities(config, inventory, now=NOW)

    work = bound["defaults"]["instruments"]["work"]
    assert work["primary"] == {
        "instrument": "zai-live",
        "model": "zai-coding-plan/glm-5.3-flash",
        "provider": "z.ai",
    }
    assert work["fallbacks"][0]["instrument"] == "codex-cli"
    receipt = bound["defaults"]["routing_receipts"]["work"]
    assert receipt["evidence_at"] == "2026-08-30T12:00:00Z"
    assert receipt["requirements"]["load_bearing"] is True
    assert config["defaults"].get("instruments") is None


def test_binding_removes_agent_override_that_would_bypass_receipt() -> None:
    config = {
        "defaults": {
            "phase_requirements": {
                "work": {"required_capabilities": ["file_editing"]},
            }
        },
        "agents": [
            {
                "name": "canyon",
                "instruments": {
                    "work": {"primary": {"instrument": "stale-unverified"}}
                },
            }
        ],
    }
    inventory = {
        "profiles": [
            _profile(
                "verified",
                provider="openai",
                model="gpt-5.6-codex",
                capabilities=["file_editing"],
            )
        ]
    }

    bound = bind_config_to_capabilities(config, inventory, now=NOW)

    assert "work" not in bound["agents"][0].get("instruments", {})
    assert bound["defaults"]["routing_receipts"]["work"]["selected"][0]["name"] == "verified"


def test_concrete_score_binding_replaces_routes_and_embeds_receipts(
    tmp_path: Path,
) -> None:
    score = {
        "name": "targeted-work-canyon",
        "instrument": "stale-unverified",
        "instrument_fallbacks": ["stale-fallback"],
        "instruments": {"stale": {"profile": "stale-unverified", "config": {}}},
        "sheet": {
            "per_sheet_instruments": {3: "stale-unverified", 4: "cli", 11: "cli"},
            "per_sheet_fallbacks": {3: ["stale-fallback"], 4: [], 11: []},
        },
        "prompt": {
            "variables": {
                "marianne_agent": {
                    "schema_version": 1,
                    "agent_id": "canyon",
                    "score_shape": "targeted-work",
                    "phase_requirements": {
                        "work": {
                            "required_capabilities": ["file_editing"],
                            "load_bearing": True,
                        }
                    },
                    "routing_receipts": {},
                }
            }
        },
    }
    inventory = {
        "profiles": [
            _profile(
                "verified",
                provider="openai",
                model="gpt-5.6-codex",
                capabilities=["file_editing"],
            ),
            _profile(
                "fallback",
                provider="z.ai",
                model="zai-coding-plan/glm-5.3-flash",
                capabilities=["file_editing"],
                priority=200,
            ),
        ]
    }

    run_workspace = tmp_path / "engagement-workspace"
    bound = bind_score_to_capabilities(
        score,
        inventory,
        run_workspace=run_workspace,
        now=NOW,
    )

    assert bound["instrument"] == "verified--gpt-5.6-codex"
    assert bound["instrument_fallbacks"] == [
        "fallback--glm-5.3-flash"
    ]
    assert bound["instruments"]["verified--gpt-5.6-codex"] == {
        "profile": "verified",
        "config": {"model": "gpt-5.6-codex", "provider": "openai"},
    }
    assert bound["sheet"]["per_sheet_instruments"][3] == "verified--gpt-5.6-codex"
    assert bound["sheet"]["per_sheet_instruments"][4] == "cli"
    assert bound["sheet"]["per_sheet_fallbacks"][4] == []
    contract = bound["prompt"]["variables"]["marianne_agent"]
    assert contract["routing_receipts"]["work"]["selected"][0]["name"] == "verified"
    assert contract["run_workspace"] == str(run_workspace)
    assert bound["workspace"] == str(run_workspace)
    assert score["instrument"] == "stale-unverified"


def test_score_binding_rejects_workspace_with_prior_lifecycle_evidence(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "used-workspace"
    (workspace / "cycle-state").mkdir(parents=True)
    score = {
        "prompt": {
            "variables": {
                "marianne_agent": {
                    "schema_version": 1,
                    "agent_id": "canyon",
                    "score_shape": "targeted-work",
                    "phase_requirements": {"work": {"required_capabilities": []}},
                    "routing_receipts": {},
                }
            }
        },
        "sheet": {},
    }

    with pytest.raises(CapabilityResolutionError, match="new engagement workspace"):
        bind_score_to_capabilities(
            score,
            {"profiles": []},
            run_workspace=workspace,
            now=NOW,
        )
