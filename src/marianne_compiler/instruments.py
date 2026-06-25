"""Instrument resolver — produces per-agent per-sheet instrument assignments.

Resolution order:
1. Start with defaults for each phase type (recon, plan, work, etc.)
2. Apply per-agent overrides
3. For each sheet, resolve the primary + explicit fallback chain
4. Emit score-local instrument ALIASES + per_sheet assignments in the score

Aliases (#214): a fallback entry like ``{instrument: openrouter, model: X}``
carries per-entry model config. Flattening chains to bare instrument NAMES
collapsed four distinct openrouter+model entries into one and ran profile
DEFAULT models (the name-only-resolution trap). The resolver now emits a
score-level ``instruments:`` alias map — one alias per distinct
(instrument, model) pair — and every chain references aliases, preserving
the declared depth and per-entry models end-to-end.

Post-#347 shape: scores carry ``instrument:`` (a name/alias), never a
``backend:`` dict — execution is configured exclusively through the
instrument plugin system. The old ``backend_type_map`` (which squashed
opencode/gemini-cli to claude_cli and produced broken type+model
combinations) is gone.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from marianne_compiler.sheets import SHEET_PHASE, SHEETS_PER_CYCLE

_logger = logging.getLogger(__name__)

# Map phase names to the instrument tier they should use from defaults
PHASE_TIER_MAP: dict[str, str] = {
    "recon": "recon",
    "plan": "plan",
    "work": "work",
    "temperature_check": "cli",
    "integration": "integration",
    "play": "play",
    "inspect": "inspect",
    "aar": "aar",
    "consolidate": "consolidate",
    "reflect": "reflect",
    "maturity_check": "cli",
    "resurrect": "resurrect",
}


def _model_slug(model: str) -> str:
    """Filesystem/YAML-safe slug for a model string (provider prefix dropped)."""
    tail = model.rsplit("/", 1)[-1]
    return re.sub(r"[^a-zA-Z0-9.]+", "-", tail).strip("-").lower()


def _entry_instrument(entry: dict[str, Any] | str) -> str:
    """Return the profile name referenced by an instrument entry."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return str(entry.get("instrument", ""))
    return ""


def _entry_key(entry: dict[str, Any] | str) -> tuple[str, str, str]:
    """Dedup key that preserves model/provider-distinct aliases."""
    if isinstance(entry, str):
        return (entry, "", "")
    if isinstance(entry, dict):
        return (
            str(entry.get("instrument", "")),
            str(entry.get("model", "")),
            str(entry.get("provider", "")),
        )
    return ("", "", "")


def _filter_tier_for_availability(
    tier_config: dict[str, Any],
    available_instruments: set[str],
    *,
    inherited_tier: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a tier with unavailable instruments removed.

    The first available entry becomes primary. Fallbacks are explicit only;
    no catalog tail is synthesized here.
    """
    candidates: list[dict[str, Any] | str] = []
    primary = tier_config.get("primary")
    inherited_primary = (inherited_tier or {}).get("primary")
    if primary:
        candidates.append(primary)
        if (
            inherited_primary
            and _entry_instrument(primary) not in available_instruments
            and _entry_key(inherited_primary) != _entry_key(primary)
        ):
            candidates.append(inherited_primary)
    elif inherited_primary:
        candidates.append(inherited_primary)

    raw_fallbacks = tier_config.get("fallbacks")
    if raw_fallbacks is None and inherited_tier is not None:
        raw_fallbacks = inherited_tier.get("fallbacks", [])
    if isinstance(raw_fallbacks, list):
        candidates.extend(raw_fallbacks)

    filtered: list[dict[str, Any] | str] = []
    seen: set[tuple[str, str, str]] = set()
    for entry in candidates:
        instrument = _entry_instrument(entry)
        key = _entry_key(entry)
        if not instrument or instrument not in available_instruments or key in seen:
            continue
        filtered.append(entry)
        seen.add(key)

    if not filtered:
        return {}

    resolved = dict(tier_config)
    resolved["primary"] = filtered[0]
    resolved["fallbacks"] = filtered[1:]
    return resolved


def filter_config_to_available_instruments(
    config: dict[str, Any],
    available_instruments: set[str],
) -> dict[str, Any]:
    """Filter compiler instrument declarations to doctor-available profiles.

    This is used by ``mzt compile --preset generic-fleet`` after the CLI has
    collected instrument readiness from the same profile/binary checks as
    ``mzt doctor``. The compiler core stays deterministic: callers choose
    whether to apply environment filtering.
    """
    if not available_instruments:
        return config

    import copy

    filtered_config = copy.deepcopy(config)
    defaults = filtered_config.get("defaults", {})
    default_instruments = defaults.get("instruments", {})
    if not isinstance(default_instruments, dict):
        return filtered_config

    original_default_instruments = copy.deepcopy(default_instruments)
    for tier, tier_config in list(default_instruments.items()):
        if not isinstance(tier_config, dict):
            continue
        filtered_tier = _filter_tier_for_availability(
            tier_config,
            available_instruments,
        )
        if filtered_tier:
            default_instruments[tier] = filtered_tier
        else:
            default_instruments.pop(tier, None)

    for agent in filtered_config.get("agents", []):
        if not isinstance(agent, dict):
            continue
        agent_instruments = agent.get("instruments")
        if not isinstance(agent_instruments, dict):
            continue
        for tier, tier_config in list(agent_instruments.items()):
            if not isinstance(tier_config, dict):
                continue
            inherited_tier = default_instruments.get(tier)
            if not isinstance(inherited_tier, dict):
                inherited_tier = original_default_instruments.get(tier)
            filtered_tier = _filter_tier_for_availability(
                tier_config,
                available_instruments,
                inherited_tier=(
                    inherited_tier if isinstance(inherited_tier, dict) else None
                ),
            )
            if filtered_tier:
                agent_instruments[tier] = filtered_tier
            else:
                agent_instruments.pop(tier, None)
        if not agent_instruments:
            agent.pop("instruments", None)

    return filtered_config


class InstrumentResolver:
    """Resolves per-sheet instrument assignments with deep fallback chains.

    Produces a matrix of primary instruments and fallback chains for every
    sheet in the cycle. Fallback chains are exactly the fallbacks declared for
    the resolved tier: the compiler does not append the whole instrument
    catalog to unrelated sheets.
    """

    def resolve(
        self,
        agent_def: dict[str, Any],
        defaults: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve instrument assignments for an agent.

        Args:
            agent_def: Agent definition with optional instrument overrides.
            defaults: Global defaults with instrument definitions per tier.

        Returns:
            Dict with keys:
                ``instrument``: str — score-level primary (work tier) alias
                ``instruments``: dict[str, dict] — score-local alias map
                    (alias -> {profile, config}); empty when no entry
                    needs per-entry config
                ``instrument_fallbacks``: list[str] — score-level fallbacks
                ``per_sheet_instruments``: dict[int, str] — per-sheet primary
                ``per_sheet_instrument_config``: dict[int, dict] — per-sheet config
                ``per_sheet_fallbacks``: dict[int, list[str]] — per-sheet
                    fallback chains, declared depth preserved via aliases
        """
        default_instruments = defaults.get("instruments", {})
        agent_instruments = agent_def.get("instruments", {})

        self._aliases: dict[str, dict[str, Any]] = {}

        per_sheet_instruments: dict[int, str] = {}
        per_sheet_config: dict[int, dict[str, Any]] = {}
        per_sheet_fallbacks: dict[int, list[str]] = {}

        for sheet_num in range(1, SHEETS_PER_CYCLE + 1):
            phase = SHEET_PHASE.get(sheet_num, "work")
            tier = PHASE_TIER_MAP.get(phase, "work")

            # Resolve: agent override > default for this tier
            resolved = self._resolve_for_tier(
                tier, agent_instruments, default_instruments
            )

            if resolved:
                primary = resolved.get("primary", {})
                primary_alias = self._alias_for(primary)
                if primary_alias:
                    per_sheet_instruments[sheet_num] = primary_alias

                # Timeout is per-sheet (orthogonal to the alias's model)
                timeout = primary.get("timeout_seconds", 0)
                if timeout:
                    per_sheet_config[sheet_num] = {"timeout_seconds": timeout}

                # Build fallback chain from the tier's explicit declarations
                # only. This keeps each sheet on instruments chosen for its
                # phase and avoids leaking unrelated tool surfaces.
                fallbacks = self._build_fallback_chain(
                    resolved.get("fallbacks", []),
                    exclude=primary_alias,
                )
                if fallbacks:
                    per_sheet_fallbacks[sheet_num] = fallbacks

        # Score-level primary: the work tier's alias (post-#347: a name,
        # never a backend dict).
        work_tier = self._resolve_for_tier(
            "work", agent_instruments, default_instruments
        )
        primary_instrument = (
            self._alias_for(work_tier.get("primary", {})) or "claude-code"
        )

        # Score-level fallbacks mirror the work tier. Per-sheet fallbacks are
        # emitted for every generated sheet, so this is mostly a compatibility
        # surface for older readers that only inspect score-level fallbacks.
        score_fallbacks = self._build_fallback_chain(
            work_tier.get("fallbacks", []),
            exclude=primary_instrument,
        )

        return {
            "instrument": primary_instrument,
            "instruments": {
                alias: spec
                for alias, spec in self._aliases.items()
                if spec["config"]  # bare profile references need no alias
            },
            "instrument_fallbacks": score_fallbacks,
            "per_sheet_instruments": per_sheet_instruments,
            "per_sheet_instrument_config": per_sheet_config,
            "per_sheet_fallbacks": per_sheet_fallbacks,
        }

    def _alias_for(self, entry: dict[str, Any] | str) -> str:
        """Return the alias name for an instrument entry, registering it.

        A bare instrument (no model/provider config) aliases to its own
        profile name. An entry with a model gets a distinct
        ``{instrument}--{model-slug}`` alias carrying the model config —
        this is what keeps two openrouter entries with different models
        distinct in a fallback chain.
        """
        if isinstance(entry, str):
            name = entry
            model = ""
            provider = ""
        elif isinstance(entry, dict):
            name = entry.get("instrument", "")
            model = entry.get("model", "")
            provider = entry.get("provider", "")
        else:
            return ""
        if not name:
            return ""

        config: dict[str, Any] = {}
        if model:
            config["model"] = model
        if provider:
            config["provider"] = provider

        alias = name if not config else f"{name}--{_model_slug(model or provider)}"
        existing = self._aliases.get(alias)
        if existing is None:
            self._aliases[alias] = {"profile": name, "config": config}
        return alias

    def _resolve_for_tier(
        self,
        tier: str,
        agent_instruments: dict[str, Any],
        default_instruments: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve the instrument config for a tier.

        Agent overrides take precedence over defaults.
        """
        # Check agent-level override for this tier
        if tier in agent_instruments:
            agent_tier = agent_instruments[tier]
            if isinstance(agent_tier, dict):
                # Merge: agent primary overrides, inherit default fallbacks
                default_tier = default_instruments.get(tier, {})
                merged = dict(default_tier) if isinstance(default_tier, dict) else {}
                merged.update(agent_tier)
                # Inherit fallbacks from defaults if not specified
                if "fallbacks" not in agent_tier and isinstance(default_tier, dict):
                    merged["fallbacks"] = default_tier.get("fallbacks", [])
                return merged

        # Fall back to defaults
        default_tier = default_instruments.get(tier)
        if isinstance(default_tier, dict):
            return dict(default_tier)
        if tier == "integration":
            return self._resolve_for_tier("work", agent_instruments, default_instruments)
        if tier == "cli":
            return {"primary": {"instrument": "cli"}}
        return {}

    def _build_fallback_chain(
        self,
        explicit_fallbacks: list[dict[str, Any]],
        exclude: str = "",
    ) -> list[str]:
        """Build a fallback chain of ALIASES (#214).

        Each declared fallback entry gets its own alias, so two entries on
        the same instrument with different models stay distinct. The chain
        contains no implicit catalog tail; if a sheet should be allowed to
        fall back to an instrument, the tier must say so explicitly.
        """
        chain: list[str] = []
        seen: set[str] = set()

        if exclude:
            seen.add(exclude)

        # Add explicit fallbacks first, one alias per declared entry
        for fb in explicit_fallbacks:
            alias = self._alias_for(fb)
            if alias and alias not in seen:
                chain.append(alias)
                seen.add(alias)

        return chain
