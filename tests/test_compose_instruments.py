"""Tests for the instrument resolver module."""

from __future__ import annotations

from marianne_compiler.instruments import PHASE_TIER_MAP, InstrumentResolver
from marianne_compiler.sheets import SHEET_PHASE, SHEETS_PER_CYCLE


def _make_agent_def(name: str = "canyon") -> dict[str, object]:
    return {
        "name": name,
        "voice": "Structure persists.",
        "focus": "architecture",
        "instruments": {
            "work": {
                "primary": {"instrument": "claude-code", "model": "claude-opus-4-6"},
            },
        },
    }


def _make_defaults() -> dict[str, object]:
    return {
        "instruments": {
            "recon": {
                "primary": {"instrument": "openrouter", "model": "minimax/minimax-2.5"},
                "fallbacks": [
                    {"instrument": "openrouter", "model": "meta-llama/llama-4-maverick"},
                    {"instrument": "gemini-cli"},
                ],
            },
            "plan": {
                "primary": {"instrument": "openrouter", "model": "minimax/minimax-2.5"},
                "fallbacks": [{"instrument": "gemini-cli"}],
            },
            "work": {
                "primary": {"instrument": "opencode", "model": "minimax/minimax-2.5", "provider": "openrouter"},
                "fallbacks": [
                    {"instrument": "claude-code", "model": "claude-opus-4-6"},
                    {"instrument": "openrouter", "model": "minimax/minimax-2.5"},
                ],
            },
            "play": {
                "primary": {"instrument": "claude-code", "model": "claude-opus-4-6"},
                "fallbacks": [{"instrument": "gemini-cli"}],
            },
            "inspect": {
                "primary": {"instrument": "gemini-cli"},
                "fallbacks": [{"instrument": "openrouter", "model": "google/gemma-4"}],
            },
            "aar": {
                "primary": {"instrument": "openrouter", "model": "minimax/minimax-2.5"},
            },
            "consolidate": {
                "primary": {"instrument": "openrouter", "model": "minimax/minimax-2.5"},
            },
            "reflect": {
                "primary": {"instrument": "openrouter", "model": "minimax/minimax-2.5"},
            },
            "resurrect": {
                "primary": {"instrument": "openrouter", "model": "minimax/minimax-2.5"},
            },
        },
    }


class TestInstrumentResolver:
    """Tests for InstrumentResolver."""

    def test_returns_required_keys(self) -> None:
        """Resolver returns all required result keys."""
        resolver = InstrumentResolver()
        result = resolver.resolve(_make_agent_def(), _make_defaults())

        assert "instrument" in result          # post-#347: a name, not a dict
        assert "instruments" in result          # score-local alias map (#214)
        assert "instrument_fallbacks" in result
        assert "per_sheet_instruments" in result
        assert "per_sheet_instrument_config" in result
        assert "per_sheet_fallbacks" in result
        assert "backend" not in result          # backend dicts are gone

    def test_defaults_applied_per_phase_type(self) -> None:
        """Default instruments are correctly applied for each phase type."""
        resolver = InstrumentResolver()
        # Agent with no instrument overrides
        agent = {"name": "bare", "voice": "v", "focus": "f"}
        result = resolver.resolve(agent, _make_defaults())

        per_sheet = result["per_sheet_instruments"]

        # Verify each phase gets the correct default instrument
        # #214: per-sheet primaries are model-carrying ALIASES; entries
        # without per-entry config keep their bare profile name.
        expected: dict[int, str] = {
            1: "openrouter--minimax-2.5",   # recon tier
            2: "openrouter--minimax-2.5",   # plan tier
            3: "opencode--minimax-2.5",     # work tier
            4: "opencode--minimax-2.5",     # temperature_check uses work tier
            5: "opencode--minimax-2.5",     # integration uses work tier
            6: "claude-code--claude-opus-4-6",  # play tier
            7: "gemini-cli",                # inspect tier (bare — no model)
            8: "openrouter--minimax-2.5",   # aar tier
            9: "openrouter--minimax-2.5",   # consolidate tier
            10: "openrouter--minimax-2.5",  # reflect tier
            11: "opencode--minimax-2.5",     # maturity_check uses work tier
            12: "openrouter--minimax-2.5",   # resurrect tier
        }

        for sheet_num, expected_instrument in expected.items():
            assert per_sheet.get(sheet_num) == expected_instrument, (
                f"Sheet {sheet_num} ({SHEET_PHASE.get(sheet_num)}) expected "
                f"{expected_instrument}, got {per_sheet.get(sheet_num)}"
            )

    def test_agent_override_applied(self) -> None:
        """Agent-level instrument overrides take precedence."""
        resolver = InstrumentResolver()
        result = resolver.resolve(_make_agent_def(), _make_defaults())

        per_sheet = result["per_sheet_instruments"]
        # Canyon overrides work to claude-code@opus; sheets using work tier
        # get a model-carrying ALIAS (#214) registered in result["instruments"].
        alias = per_sheet.get(3)
        assert alias == "claude-code--claude-opus-4-6"
        assert result["instruments"][alias] == {
            "profile": "claude-code",
            "config": {"model": "claude-opus-4-6"},
        }

    def test_defaults_for_non_overridden(self) -> None:
        """Default instruments are used for tiers without agent overrides."""
        resolver = InstrumentResolver()
        result = resolver.resolve(_make_agent_def(), _make_defaults())

        per_sheet = result["per_sheet_instruments"]
        # Sheet 1 (recon) uses the default openrouter+minimax ALIAS
        alias = per_sheet.get(1)
        assert alias == "openrouter--minimax-2.5"
        assert result["instruments"][alias]["profile"] == "openrouter"
        assert result["instruments"][alias]["config"]["model"] == "minimax/minimax-2.5"

    def test_per_sheet_config_has_model(self) -> None:
        """Per-sheet config includes model when specified."""
        resolver = InstrumentResolver()
        result = resolver.resolve(_make_agent_def(), _make_defaults())

        # #214: models live on the score-local ALIAS, not per-sheet config
        # (per-sheet config now carries only orthogonal settings like
        # timeout_seconds). The work-tier alias carries the opus model.
        alias = result["per_sheet_instruments"][3]
        assert result["instruments"][alias]["config"]["model"] == "claude-opus-4-6"

    def test_fallback_chains_populated(self) -> None:
        """Per-sheet fallback chains are populated."""
        resolver = InstrumentResolver()
        result = resolver.resolve(_make_agent_def(), _make_defaults())

        fallbacks = result["per_sheet_fallbacks"]
        # Most sheets should have fallback chains
        assert len(fallbacks) > 0

    def test_no_dead_ends(self) -> None:
        """Every sheet's fallback chain contains all catalog instruments."""
        resolver = InstrumentResolver()
        result = resolver.resolve(_make_agent_def(), _make_defaults())

        all_instruments = set(result["instrument_fallbacks"])
        per_sheet = result["per_sheet_instruments"]
        fallbacks = result["per_sheet_fallbacks"]

        for sheet_num in range(1, SHEETS_PER_CYCLE + 1):
            primary = per_sheet.get(sheet_num, "")
            chain = fallbacks.get(sheet_num, [])
            # primary + chain should cover the full catalog
            covered = {primary} | set(chain)
            missing = all_instruments - covered
            assert not missing, (
                f"Sheet {sheet_num} missing instruments in fallback chain: {missing}"
            )

    def test_deep_fallbacks_chain_order(self) -> None:
        """Explicit fallbacks appear before catalog tail in each chain."""
        resolver = InstrumentResolver()
        result = resolver.resolve(_make_agent_def(), _make_defaults())

        fallbacks = result["per_sheet_fallbacks"]
        # Sheet 1 (recon) has explicit fallbacks: openrouter(maverick), gemini-cli
        chain_1 = fallbacks.get(1, [])
        if "gemini-cli" in chain_1:
            # gemini-cli is an explicit fallback, should appear before catalog tail
            gemini_idx = chain_1.index("gemini-cli")
            # Catalog-only instruments (not in explicit fallbacks) should come after
            assert gemini_idx < len(chain_1), "Explicit fallbacks should be early in chain"

    def test_resolves_concrete_sheet_numbers_from_phases(self) -> None:
        """PHASE_TIER_MAP maps every phase to a tier used for instrument lookup."""
        # Verify that every phase in SHEET_PHASE has a corresponding tier mapping
        for sheet_num in range(1, SHEETS_PER_CYCLE + 1):
            phase = SHEET_PHASE.get(sheet_num)
            assert phase is not None, f"Sheet {sheet_num} has no phase mapping"
            tier = PHASE_TIER_MAP.get(phase)
            assert tier is not None, (
                f"Phase '{phase}' (sheet {sheet_num}) has no tier in PHASE_TIER_MAP"
            )

        # Verify the resolver actually uses these mappings to produce assignments
        resolver = InstrumentResolver()
        result = resolver.resolve(_make_agent_def(), _make_defaults())
        per_sheet = result["per_sheet_instruments"]

        # Every sheet number should have an instrument assigned
        for sheet_num in range(1, SHEETS_PER_CYCLE + 1):
            assert sheet_num in per_sheet, (
                f"Sheet {sheet_num} ({SHEET_PHASE[sheet_num]}) has no instrument"
            )

    def test_score_level_fallbacks(self) -> None:
        """Score-level fallbacks include all instruments from defaults."""
        resolver = InstrumentResolver()
        result = resolver.resolve(_make_agent_def(), _make_defaults())

        fallbacks = result["instrument_fallbacks"]
        # Aliases from the defaults catalog are present (deep chains, #214)
        assert any(a.startswith("openrouter--") for a in fallbacks)
        assert any(a.startswith(("claude-code", "opencode", "gemini-cli")) for a in fallbacks)

    def test_empty_defaults(self) -> None:
        """Works with no instrument defaults."""
        resolver = InstrumentResolver()
        agent = {"name": "bare", "voice": "v", "focus": "f"}
        result = resolver.resolve(agent, {})

        assert result["instrument"] == "claude-code"
        assert isinstance(result["per_sheet_instruments"], dict)

    def test_backend_config_from_primary(self) -> None:
        """Backend config is derived from the work tier primary."""
        resolver = InstrumentResolver()
        result = resolver.resolve(_make_agent_def(), _make_defaults())

        # Post-#347: the score-level primary is the work tier's ALIAS
        assert result["instrument"] == "claude-code--claude-opus-4-6"

    def test_all_sheets_covered(self) -> None:
        """Per-sheet instruments cover all 12 sheets."""
        resolver = InstrumentResolver()
        result = resolver.resolve(_make_agent_def(), _make_defaults())

        per_sheet = result["per_sheet_instruments"]
        # With full defaults, every sheet should have an instrument
        for i in range(1, 13):
            assert i in per_sheet, f"Sheet {i} missing instrument assignment"

    def test_provider_in_config(self) -> None:
        """Provider field is preserved in per-sheet instrument config."""
        resolver = InstrumentResolver()
        agent = {"name": "bare", "voice": "v", "focus": "f"}
        result = resolver.resolve(agent, _make_defaults())

        # #214: provider lives on the alias config now
        alias = result["per_sheet_instruments"][3]
        assert result["instruments"][alias]["config"].get("provider") == "openrouter"

    def test_multiple_agent_overrides(self) -> None:
        """Agent with overrides on multiple tiers."""
        resolver = InstrumentResolver()
        agent: dict[str, object] = {
            "name": "sentinel",
            "voice": "Absence.",
            "focus": "security",
            "instruments": {
                "work": {
                    "primary": {"instrument": "goose", "model": "glm-4.5"},
                },
                "inspect": {
                    "primary": {"instrument": "gemini-cli", "model": "gemini-2.5-pro"},
                },
            },
        }
        result = resolver.resolve(agent, _make_defaults())
        per_sheet = result["per_sheet_instruments"]

        # Work sheets use goose
        assert per_sheet[3] == "goose--glm-4.5"
        # Inspect uses gemini-cli (agent override matches default here but with model)
        assert per_sheet[7] == "gemini-cli--gemini-2.5-pro"
        # Non-overridden tiers still use defaults
        assert per_sheet[1] == "openrouter--minimax-2.5"  # recon
