"""Deterministic binding of phase requirements to live instrument evidence."""

from __future__ import annotations

import copy
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from marianne_compiler.instruments import InstrumentResolver
from marianne_compiler.sheets import PHASE_MAP


class CapabilityResolutionError(ValueError):
    """No live instrument route can satisfy a phase contract."""


_RELIABILITY_RANK = {
    "high": 0,
    "standard": 1,
    "variable": 2,
    "supplementary": 3,
}
_LATENCY_RANK = {"low": 0, "normal": 1, "variable": 2, "queued": 3, "high": 4}
_RELIABILITY_CLASSES = frozenset(_RELIABILITY_RANK)
_DJ_PROFILE = re.compile(r"^musician-.+$", re.IGNORECASE)


def resolve_phase_routes(
    phase: str,
    requirements: dict[str, Any],
    inventory: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Resolve one phase against verified profiles and retain rejection evidence."""
    evidence_time = (now or datetime.now(UTC)).astimezone(UTC)
    raw_profiles = inventory.get("profiles", [])
    if not isinstance(raw_profiles, list):
        raise CapabilityResolutionError("Capability inventory profiles must be a list")

    required = {
        str(value)
        for value in requirements.get("required_capabilities", [])
        if str(value)
    }
    min_context = int(requirements.get("min_context_tokens", 0) or 0)
    load_bearing = bool(requirements.get("load_bearing", False))
    max_age = timedelta(hours=float(requirements.get("max_evidence_age_hours", 24)))
    allowed_providers = {
        _provider_key(str(value))
        for value in requirements.get("allowed_providers", [])
        if str(value)
    }

    eligible: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for raw_profile in raw_profiles:
        if not isinstance(raw_profile, dict):
            continue
        profile = copy.deepcopy(raw_profile)
        name = str(profile.get("name", "")).strip()
        reasons = _rejection_reasons(
            profile,
            required=required,
            min_context=min_context,
            allowed_providers=allowed_providers,
            evidence_time=evidence_time,
            max_age=max_age,
        )
        if reasons:
            rejected.append({"name": name or "<unnamed>", "reasons": reasons})
            continue
        eligible.append(profile)

    eligible.sort(key=_profile_rank)
    reliable = [profile for profile in eligible if not _is_supplementary(profile)]
    supplementary = [profile for profile in eligible if _is_supplementary(profile)]
    if load_bearing and supplementary and not reliable:
        raise CapabilityResolutionError(
            f"Phase '{phase}' is load-bearing but only supplementary routes are available"
        )
    ordered = [*reliable, *supplementary]
    if not ordered:
        detail = "; ".join(
            f"{item['name']}: {', '.join(item['reasons'])}"
            for item in sorted(rejected, key=lambda item: item["name"])
        )
        raise CapabilityResolutionError(
            f"No live instrument route satisfies phase '{phase}'"
            + (f" ({detail})" if detail else "")
        )

    max_fallbacks = requirements.get("max_fallbacks")
    if max_fallbacks is not None:
        limit = 1 + max(0, int(max_fallbacks))
        ordered = ordered[:limit]

    selected = [_selected_profile(profile, index=index) for index, profile in enumerate(ordered)]
    return {
        "schema_version": 1,
        "phase": phase,
        "evidence_at": _format_time(evidence_time),
        "requirements": copy.deepcopy(requirements),
        "selected": selected,
        "rejected": sorted(rejected, key=lambda item: item["name"]),
        "operating_cost_notice": (
            "Metered token price does not include latency, queues, quotas, "
            "rate limits, reliability, or human waiting time."
        ),
    }


def bind_config_to_capabilities(
    config: dict[str, Any],
    inventory: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Materialize compiler instrument tiers from semantic phase requirements."""
    bound = copy.deepcopy(config)
    defaults = bound.setdefault("defaults", {})
    if not isinstance(defaults, dict):
        raise CapabilityResolutionError("Compiler defaults must be a mapping")
    requirements_by_phase = defaults.get("phase_requirements", {})
    if not isinstance(requirements_by_phase, dict):
        raise CapabilityResolutionError("defaults.phase_requirements must be a mapping")

    instruments = defaults.setdefault("instruments", {})
    receipts = defaults.setdefault("routing_receipts", {})
    if not isinstance(instruments, dict) or not isinstance(receipts, dict):
        raise CapabilityResolutionError("Compiler instrument and receipt sections must map")

    bound_tiers: set[str] = set()
    for phase in sorted(requirements_by_phase):
        phase_name = str(phase)
        if phase_name not in PHASE_MAP:
            raise CapabilityResolutionError(f"Unknown lifecycle phase '{phase_name}'")
        if phase_name in {"temperature_check", "maturity_check"}:
            raise CapabilityResolutionError(
                f"Cannot capability-bind deterministic CLI phase '{phase_name}'"
            )
        requirements = requirements_by_phase[phase]
        if not isinstance(requirements, dict):
            raise CapabilityResolutionError(
                f"Phase requirements for '{phase}' must be a mapping"
            )
        receipt = resolve_phase_routes(
            phase_name,
            requirements,
            inventory,
            now=now,
        )
        selected = receipt["selected"]
        instruments[phase_name] = {
            "primary": _instrument_entry(selected[0]),
            "fallbacks": [_instrument_entry(item) for item in selected[1:]],
        }
        receipts[phase_name] = receipt
        bound_tiers.add(phase_name)

    # A receipt governs the actual compiled route.  An agent-level tier with
    # the same name would otherwise override the newly verified default during
    # compilation and make the receipt false.
    agents = bound.get("agents", [])
    if isinstance(agents, list):
        for agent in agents:
            if not isinstance(agent, dict):
                continue
            overrides = agent.get("instruments")
            if not isinstance(overrides, dict):
                continue
            for tier in bound_tiers:
                overrides.pop(tier, None)
            if not overrides:
                agent.pop("instruments", None)
    return bound


def bind_score_to_capabilities(
    score: dict[str, Any],
    inventory: dict[str, Any],
    *,
    run_workspace: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Bind one already-compiled persistent-agent score to live evidence."""
    workspace = run_workspace.expanduser().resolve()
    if workspace.is_symlink():
        raise CapabilityResolutionError(
            f"Run workspace must not be a symlink: {workspace}"
        )
    cycle_state = workspace / "cycle-state"
    if cycle_state.exists():
        raise CapabilityResolutionError(
            "Run workspace already contains lifecycle evidence; choose a new "
            f"engagement workspace: {workspace}"
        )
    bound = copy.deepcopy(score)
    prompt = bound.get("prompt")
    variables = prompt.get("variables") if isinstance(prompt, dict) else None
    contract = variables.get("marianne_agent") if isinstance(variables, dict) else None
    if not isinstance(contract, dict) or contract.get("schema_version") != 1:
        raise CapabilityResolutionError(
            "Score lacks a versioned prompt.variables.marianne_agent contract"
        )
    requirements = contract.get("phase_requirements")
    if not isinstance(requirements, dict) or not requirements:
        raise CapabilityResolutionError(
            "Score's Marianne agent contract has no phase requirements to bind"
        )

    config: dict[str, Any] = {
        "defaults": {"phase_requirements": copy.deepcopy(requirements)},
        "agents": [{"name": str(contract.get("agent_id", ""))}],
    }
    route_config = bind_config_to_capabilities(config, inventory, now=now)
    defaults = route_config["defaults"]
    if not isinstance(defaults, dict):  # bind_config_to_capabilities guarantees this
        raise CapabilityResolutionError("Bound compiler defaults must be a mapping")
    resolved = InstrumentResolver().resolve(config["agents"][0], defaults)

    bound["instrument"] = resolved["instrument"]
    bound["instrument_fallbacks"] = resolved["instrument_fallbacks"]
    if resolved["instruments"]:
        bound["instruments"] = resolved["instruments"]
    else:
        bound.pop("instruments", None)
    sheet = bound.get("sheet")
    if not isinstance(sheet, dict):
        raise CapabilityResolutionError("Score sheet section must be a mapping")
    sheet["per_sheet_instruments"] = resolved["per_sheet_instruments"]
    sheet["per_sheet_instrument_config"] = resolved["per_sheet_instrument_config"]
    sheet["per_sheet_fallbacks"] = resolved["per_sheet_fallbacks"]
    contract["routing_receipts"] = defaults["routing_receipts"]
    contract["bound_at"] = _format_time((now or datetime.now(UTC)).astimezone(UTC))
    contract["run_workspace"] = str(workspace)
    bound["workspace"] = str(workspace)
    return bound


def _rejection_reasons(
    profile: dict[str, Any],
    *,
    required: set[str],
    min_context: int,
    allowed_providers: set[str],
    evidence_time: datetime,
    max_age: timedelta,
) -> list[str]:
    reasons: list[str] = []
    name = str(profile.get("name", "")).strip()
    provider = str(profile.get("provider", "")).strip()
    model = str(profile.get("model", "")).strip()
    reliability_raw = str(profile.get("reliability_class", "variable"))
    reliability = reliability_raw.strip().lower()
    if not name:
        reasons.append("missing_profile_name")
    elif _DJ_PROFILE.fullmatch(name):
        reasons.append("dj_project_profile_forbidden")
    if profile.get("available") is not True:
        reasons.append("not_live_available")
    if profile.get("invocation_contract_verified") is not True:
        reasons.append("invocation_contract_unverified")
    if profile.get("entitlement_verified") is not True:
        reasons.append("entitlement_unverified")
    if reliability_raw != reliability or reliability not in _RELIABILITY_CLASSES:
        reasons.append("invalid_reliability_class")

    verified_at = _parse_time(profile.get("verified_at"))
    if verified_at is None:
        reasons.append("missing_live_evidence_time")
    elif verified_at > evidence_time + timedelta(minutes=5):
        reasons.append("live_evidence_from_future")
    elif evidence_time - verified_at > max_age:
        reasons.append("live_evidence_stale")

    capabilities = {
        str(value) for value in profile.get("capabilities", []) if str(value)
    }
    missing = sorted(required - capabilities)
    if missing:
        reasons.append(f"missing_capabilities:{','.join(missing)}")
    context_tokens = int(profile.get("context_tokens", 0) or 0)
    if context_tokens < min_context:
        reasons.append(f"context_below_minimum:{context_tokens}<{min_context}")
    if allowed_providers and _provider_key(provider) not in allowed_providers:
        reasons.append("provider_not_allowed")
    if "glm-5.3-flash" in model.lower() and not _is_zai_provider(provider):
        reasons.append("glm_5_3_flash_requires_zai")
    return reasons


def _profile_rank(profile: dict[str, Any]) -> tuple[int, int, int, str]:
    reliability = str(profile.get("reliability_class", "variable")).strip().lower()
    latency = str(profile.get("latency_class", "variable")).strip().lower()
    return (
        _RELIABILITY_RANK.get(reliability, 2),
        int(profile.get("priority", 100) or 100),
        _LATENCY_RANK.get(latency, 2),
        str(profile.get("name", "")),
    )


def _selected_profile(profile: dict[str, Any], *, index: int) -> dict[str, Any]:
    notes: list[str] = []
    if _is_supplementary(profile):
        notes.append("supplementary_lane_not_primary")
    if str(profile.get("metered_cost", "")).lower() in {"free", "zero", "subscription"}:
        notes.append("zero_or_included_metering_is_not_zero_operating_cost")
    return {
        "rank": index + 1,
        "name": str(profile["name"]),
        "provider": str(profile.get("provider", "")),
        "model": str(profile.get("model", "")),
        "capabilities": sorted(str(value) for value in profile.get("capabilities", [])),
        "context_tokens": int(profile.get("context_tokens", 0) or 0),
        "reliability_class": str(profile.get("reliability_class", "variable")),
        "latency_class": str(profile.get("latency_class", "variable")),
        "metered_cost": str(profile.get("metered_cost", "unknown")),
        "verified_at": str(profile.get("verified_at", "")),
        "notes": notes,
    }


def _instrument_entry(selected: dict[str, Any]) -> dict[str, str]:
    entry = {"instrument": str(selected["name"])}
    if selected.get("model"):
        entry["model"] = str(selected["model"])
    if selected.get("provider"):
        entry["provider"] = str(selected["provider"])
    return entry


def _is_supplementary(profile: dict[str, Any]) -> bool:
    return (
        str(profile.get("reliability_class", "variable")).strip().lower()
        == "supplementary"
    )


def _provider_key(provider: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", provider.lower())


def _is_zai_provider(provider: str) -> bool:
    return _provider_key(provider) in {"zai", "zaicodingplan"}


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_time(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "CapabilityResolutionError",
    "bind_config_to_capabilities",
    "bind_score_to_capabilities",
    "resolve_phase_routes",
]
