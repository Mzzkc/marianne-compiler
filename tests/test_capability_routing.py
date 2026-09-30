"""Tests for deterministic phase-capability instrument binding."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from marianne_compiler.capabilities import (
    CapabilityResolutionError,
    bind_config_to_capabilities,
    bind_score_to_capabilities,
    resolve_phase_routes,
)
from marianne_compiler.validations import ValidationGenerator

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


def test_concrete_score_binding_localizes_home_paths_without_retargeting_cadenza(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    canonical_agent = home / "Projects" / "AGENTS" / "agents" / "journey"
    cadenza = canonical_agent / "cadenzas" / "personal" / "active"
    cadenza.mkdir(parents=True)
    expected_files = {
        "01-task-board.md",
        "02-status.md",
        "03-urgent-directives.md",
        "04-handoffs.md",
    }
    for filename in expected_files:
        (cadenza / filename).write_text(filename)
    score = {
        "workspace": str(tmp_path / "unused"),
        "sheet": {
            "prelude": [{"file": str(canonical_agent / "identity.md")}],
            "cadenzas": {"all": [{"directory": str(cadenza)}]},
        },
        "validations": [],
        "prompt": {
            "variables": {
                "agent_identity_dir": str(canonical_agent),
                "marianne_agent": {
                    "schema_version": 1,
                    "agent_id": "journey",
                    "score_shape": "targeted-work",
                    "phase_requirements": {"work": {"required_capabilities": ["file_editing"]}},
                    "routing_receipts": {},
                },
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
            )
        ]
    }

    generated = ValidationGenerator().generate(
        {"name": "journey"},
        {
            "cadenza_completion_validation": True,
            "cadenzas": {"active": [{"phases": ["recon"]}]},
        },
        agents_dir=str(home / "Projects" / "AGENTS" / "agents"),
    )
    stock_check = next(
        item
        for item in generated
        if item.get("description") == "Cadenza completion state for journey recon"
    )
    legacy_command = stock_check["command"].replace(
        f"AGENT_DIR={canonical_agent} ", "", 1
    )
    legacy_command = legacy_command.replace(
        'agent_dir = Path(os.environ["AGENT_DIR"]).expanduser()\n', "", 1
    )
    legacy_command = legacy_command.replace(
        'cadenza = agent_dir / "cadenzas" / "personal" / "active"\n', "", 1
    )
    legacy_command = legacy_command.replace(
        "cadenza / ", 'workspace / "shared" / "active" / ',
    )
    score["validations"] = [
        {**stock_check, "command": legacy_command}
    ]

    bound = bind_score_to_capabilities(
        score,
        inventory,
        run_workspace=home / "Projects" / "WORKSPACES" / "test-bound",
        now=NOW,
    )

    expected_cadenza = str(cadenza).replace(str(home), "~", 1)
    assert bound["workspace"].startswith("~/")
    assert bound["sheet"]["prelude"][0]["file"] == str(
        canonical_agent / "identity.md"
    ).replace(str(Path.home()), "~", 1)
    assert bound["sheet"]["cadenzas"]["all"][0]["directory"] == expected_cadenza
    assert Path(expected_cadenza).expanduser() == cadenza
    assert {path.name for path in Path(expected_cadenza).expanduser().iterdir()} == expected_files
    assert bound["prompt"]["variables"]["agent_identity_dir"] == str(
        canonical_agent
    ).replace(str(home), "~", 1)
    guidance = bound["prompt"]["prompt_extensions"][0]
    expected_identity = str(canonical_agent).replace(str(home), "~", 1)
    assert f"Canonical agent memory root: {expected_identity}" in guidance
    assert (
        f"Canonical personal active cadenza (attached source): {expected_cadenza}"
        in guidance
    )
    assert "Do not copy or recreate these records under workspace/shared/active" in guidance
    assert "edit the canonical files in place" in guidance
    bound_command = bound["validations"][0]["command"]
    assert "AGENT_DIR='~/Projects/AGENTS/agents/journey'" in bound_command
    assert 'agent_dir / "cadenzas" / "personal" / "active"' in bound_command
    assert 'workspace / "shared" / "active"' not in bound_command

    workspace = Path(bound["workspace"]).expanduser()
    artifact = workspace / "cycle-state" / "journey-recon.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Observed the bounded test input.\n")
    (cadenza / "01-task-board.md").write_text(
        "| journey-T-001 | journey | done | cycle-state/journey-recon.md |\n"
    )
    (cadenza / "02-status.md").write_text(
        "journey recon cycle-state/journey-recon.md\n"
    )
    command = bound_command.replace("{workspace}", str(workspace))
    result = subprocess.run(
        ["bash", "-c", command],
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "HOME": str(home)},
    )
    assert result.returncode == 0, result.stderr


def test_canonical_cadenza_guidance_is_scoped_to_attached_sheets(
    tmp_path: Path,
) -> None:
    identity_dir = tmp_path / "AGENTS" / "agents" / "journey"
    active_dir = identity_dir / "cadenzas" / "personal" / "active"
    score = {
        "sheet": {
            "per_sheet_instrument_config": {
                1: {"timeout_seconds": 300, "temperature": 0.2},
                3: {"timeout_seconds": 600},
            },
            "cadenzas": {
                1: [{"directory": str(active_dir), "required": True}],
                2: [{"directory": "{{workspace}}/shared/active", "required": True}],
            }
        },
        "prompt": {
            "variables": {
                "agent_identity_dir": str(identity_dir),
                "marianne_agent": {
                    "schema_version": 1,
                    "agent_id": "journey",
                    "score_shape": "targeted-work",
                    "phase_requirements": {
                        "work": {"required_capabilities": ["file_editing"]}
                    },
                    "routing_receipts": {},
                },
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
            )
        ]
    }

    bound = bind_score_to_capabilities(
        score, inventory, run_workspace=tmp_path / "run", now=NOW
    )

    extensions = bound["sheet"]["prompt_extensions"]
    assert set(extensions) == {1}
    assert "Canonical personal active cadenza (attached source):" in extensions[1][0]
    assert "prompt_extensions" not in bound["prompt"]
    assert "prompt_extensions" not in score["sheet"]
    assert bound["sheet"]["per_sheet_instrument_config"][1] == {
        "timeout_seconds": 300,
        "temperature": 0.2,
    }
    assert bound["sheet"]["per_sheet_instrument_config"][3] == {
        "timeout_seconds": 600
    }


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
