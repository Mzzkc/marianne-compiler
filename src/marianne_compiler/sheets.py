"""Sheet composer — produces the sheet structure for agent scores.

Generates a 12-sheet cycle structure with parallel dependency phases:

    Phase 1   (sequential):   Recon -> Plan -> Work          (sheets 1-3)
    Phase 1.5 (CLI):          Temperature check (gates Play)  (sheet 4)
    Phase 2   (parallel):     Integration || Play || Inspect  (sheets 5-7)
    Phase 3   (parallel):     AAR || Consolidate -> Reflect  (sheets 8-10)
    Phase 3.5 (CLI):          Maturity check                  (sheet 11)
    Phase 4   (sequential):   Resurrect                       (sheet 12)

Total: 12 sheets per cycle.
"""

from __future__ import annotations

import logging
import shlex
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

SHEETS_PER_CYCLE = 12

# Phase name to sheet number(s) mapping
PHASE_MAP: dict[str, list[int]] = {
    "recon": [1],
    "plan": [2],
    "work": [3],
    "temperature_check": [4],
    "integration": [5],
    "play": [6],
    "inspect": [7],
    "aar": [8],
    "consolidate": [9],
    "reflect": [10],
    "maturity_check": [11],
    "resurrect": [12],
}

# Reverse: sheet number to phase name
SHEET_PHASE: dict[int, str] = {}
for _phase, _sheets in PHASE_MAP.items():
    for _s in _sheets:
        SHEET_PHASE[_s] = _phase

# CLI instrument sheets (not LLM calls)
CLI_SHEETS = {4, 11}

# Sheet descriptions
SHEET_DESCRIPTIONS: dict[int, str] = {
    1: "Recon — survey project state",
    2: "Plan — write cycle plan",
    3: "Work — execute against plan",
    4: "Temperature check — gate play phase",
    5: "Integration — merge and coordinate",
    6: "Play — explore and experiment",
    7: "Inspect — quality and security review",
    8: "AAR — after-action review",
    9: "Consolidate — memory management",
    10: "Reflect — growth and insight",
    11: "Maturity check — developmental measurement",
    12: "Resurrect — identity refresh for next cycle",
}


class SheetComposer:
    """Composes the sheet structure for an agent score.

    Takes agent definitions and default config, produces the sheet section
    of a Marianne score YAML including fan-out, dependencies, cadenzas,
    and instrument assignments.
    """

    def __init__(self, templates_dir: Path | None = None) -> None:
        self.templates_dir = templates_dir

    def compose(
        self,
        agent_def: dict[str, Any],
        defaults: dict[str, Any],
        *,
        agents_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Compose the sheet configuration for an agent score.

        Args:
            agent_def: Agent definition dict.
            defaults: Global defaults from the compiler config.
            agents_dir: Path to agents identity directory.

        Returns:
            Dict representing the ``sheet:`` section of a Marianne score.
        """
        name = agent_def["name"]
        agents_dir_path = agents_dir or Path.home() / ".marianne" / "agents"
        identity_dir = str(agents_dir_path / name)

        sheet_config: dict[str, Any] = {
            "size": 1,
            "total_items": SHEETS_PER_CYCLE,
            "descriptions": dict(SHEET_DESCRIPTIONS),
            "prelude": self._build_prelude(identity_dir, defaults),
            "cadenzas": self._build_cadenzas(identity_dir, defaults),
            "dependencies": self._build_dependencies(),
        }

        # Add command skip rules for play gating. The live score schema uses
        # `skip_when` (formerly skip_when_command).
        skip_when = self._build_skip_when(agent_def, defaults, identity_dir)
        shape_skip, prompt_extensions = self._build_score_shape(defaults, identity_dir)
        skip_when.update(shape_skip)
        if skip_when:
            sheet_config["skip_when"] = skip_when
        if prompt_extensions:
            sheet_config["prompt_extensions"] = prompt_extensions

        triggers = self._build_verdict_trigger(name, defaults)
        if triggers:
            sheet_config["triggers"] = triggers

        return sheet_config

    def _build_verdict_trigger(
        self, name: str, defaults: dict[str, Any],
    ) -> dict[int, dict[str, Any]]:
        """A machine-readable verdict after AAR, without a new model call.

        GH #463: nothing in the 12-sheet cycle produced a fixed-enum verdict
        a downstream gate could read without parsing prose. The Inspect
        sheet's ``VERDICT:`` line is enforced (ACCEPT|REWORK|PASS|FAIL|REJECT,
        GH #461) and the AAR carries ``DELTA:``; a ``run`` trigger on the AAR
        sheet's success folds them into ``cycle-state/<name>-verdict.yaml``
        under a pre-fixed rule, so the verdict is derived from the cycle's
        own evidence by a deterministic shell step. ``defaults.verdict:
        false`` turns it off.
        """
        if defaults.get("verdict", True) is False:
            return {}
        inspection = f"{{workspace}}/cycle-state/{name}-inspection.md"
        aar = f"{{workspace}}/cycle-state/{name}-aar.md"
        out = f"{{workspace}}/cycle-state/{name}-verdict.yaml"
        command = "\n".join([
            "set -eu",
            f'inspect={shlex.quote(inspection)}; aar={shlex.quote(aar)}; out={shlex.quote(out)}',
            "raw=$(grep -iE '^VERDICT:' \"$inspect\" | head -1 | "
            "sed -E 's/^VERDICT:[[:space:]]*//I' | tr '[:lower:]' '[:upper:]' | "
            "grep -oE '^(ACCEPT|REWORK|PASS|FAIL|REJECT)' || true)",
            "case \"$raw\" in",
            "  ACCEPT|PASS) verdict=ACCEPT ;;",
            "  REWORK|FAIL|REJECT) verdict=REWORK ;;",
            "  *) verdict=UNDETERMINED ;;",
            "esac",
            "delta=$(grep -iE '^DELTA:' \"$aar\" | head -1 | "
            "sed -E 's/^DELTA:[[:space:]]*//I' | cut -c1-200 || true)",
            # ACCEPT with a non-empty AAR delta still has holds to carry.
            "if [ \"$verdict\" = ACCEPT ] && [ -n \"$delta\" ] && "
            "! printf '%s' \"$delta\" | grep -qiE '^(none|no delta|n/a|-|nothing)[[:space:].]*$'; "
            "then verdict=ACCEPT_WITH_HOLDS; fi",
            "{",
            "  printf 'schema_version: 1\\nkind: marianne-cycle-verdict\\n'",
            f"  printf 'agent: {name}\\n'",
            "  printf 'verdict: %s\\n' \"$verdict\"",
            "  printf 'inspection_verdict: %s\\n' \"${raw:-MISSING}\"",
            "  printf 'aar_delta: %s\\n' \"$(printf '%s' \"$delta\" | "
            "sed -e \"s/'/''/g\" -e \"s/^/'/\" -e \"s/$/'/\")\"",
            "  printf 'rule: ACCEPT|PASS->ACCEPT; REWORK|FAIL|REJECT->REWORK; "
            "ACCEPT with a non-empty AAR DELTA->ACCEPT_WITH_HOLDS; else UNDETERMINED\\n'",
            "  printf 'decided_at: %s\\n' \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"",
            "} > \"$out.tmp\" && mv \"$out.tmp\" \"$out\"",
            "echo \"verdict: $verdict\"",
        ])
        return {
            PHASE_MAP["aar"][0]: {
                "on_success": [{
                    "run": {"command": command, "timeout_seconds": 30},
                }],
            },
        }

    def _build_score_shape(
        self,
        defaults: dict[str, Any],
        identity_dir: str,
    ) -> tuple[dict[int, dict[str, Any]], dict[int, list[str]]]:
        """Return deterministic skips and debt instructions for one run shape."""
        shape = str(defaults.get("score_shape", "full-lifecycle"))
        if shape == "full-lifecycle":
            return {}, {}
        if shape == "targeted-work":
            skipped = {4, 6, 9, 10, 11, 12}
            debt_path = f"{identity_dir}/{'.marianne/pending-lifecycle-debt.yaml'}"
            return (
                {
                    sheet: {
                        "command": "true",
                        "description": (
                            f"Targeted work defers {SHEET_PHASE[sheet]} to lifecycle integration"
                        ),
                        "timeout_seconds": 5,
                    }
                    for sheet in sorted(skipped)
                },
                {
                    8: [
                        "This is a bounded targeted engagement, not a counterfeit full lifecycle.",
                        "Update canonical recent.md with only grounded learning from this "
                        "engagement; "
                        "use the stage-1 recent-memory snapshot as the before state and record "
                        "the canonical file's SHA-256 after the write.",
                        f"Write `{debt_path}` as YAML after the immediate "
                        "AAR/recent-memory update.",
                        "Use schema_version: 1, kind: marianne-lifecycle-debt, this agent name, "
                        "status: pending, source_engagement, evidence, "
                        "recent_memory_before_snapshot, "
                        "recent_memory_before_sha256, "
                        "recent_memory_after_sha256, and pending_phases containing exactly "
                        "consolidate (consolidation), reflect (reflection), and resurrect "
                        "(resurrection). Evidence must be a non-empty list of workspace files, "
                        "each with exact path and sha256. Do not mark deferred phases complete.",
                    ]
                },
            )
        if shape == "lifecycle-integration":
            skipped = {2, 3, 4, 5, 6, 7, 8}
            metadata = f"{identity_dir}/.marianne"
            return (
                {
                    sheet: {
                        "command": "true",
                        "description": (
                            f"Lifecycle integration omits ordinary {SHEET_PHASE[sheet]} work"
                        ),
                        "timeout_seconds": 5,
                    }
                    for sheet in sorted(skipped)
                },
                {
                    1: [
                        f"Read `{metadata}/pending-lifecycle-debt.yaml` when it exists.",
                        f"Read `{metadata}/pending-seed-conflicts.yaml` when it exists.",
                        "Inventory every open lifecycle debt and portable-seed conflict; preserve "
                        "agent authority over all semantic decisions.",
                    ],
                    9: [
                        "Consolidate every grounded pending engagement into canonical "
                        "recent/profile memory. Record before/after hashes and leave unrelated "
                        "memory untouched.",
                    ],
                    10: [
                        "Reflect on pending engagements and seed conflicts. Update growth and "
                        "relationships only where the evidence warrants it.",
                    ],
                    12: [
                        "Adjudicate portable-seed conflicts as the agent, close only debt actually "
                        "integrated, and use the typed, conflict-bound agent resolution flow when "
                        "the stage-1 lifecycle inputs captured a seed conflict.",
                        "Demonstrate later recall of at least one engagement-specific learning; "
                        "name the source memory and how it changed present judgment.",
                        "Write `{{ workspace }}/cycle-state/{{ agent_name }}-lifecycle-integration-"
                        "receipt.yaml` with schema_version: 1, kind: "
                        "marianne-lifecycle-integration, "
                        "this agent name, status: integrated, source_debt_sha256, source_memory: "
                        "recent.md, closed_debt, memory_before_sha256, memory_after_sha256, "
                        "optional "
                        "seed_resolution_receipt, and typed later_recall with source_engagement, "
                        "source_evidence_sha256, recalled_learning, and present_application. The "
                        "before hash must continue the captured source debt and the after hash "
                        "must "
                        "match canonical recent.md after a real transition.",
                        f"Update `{metadata}/pending-lifecycle-debt.yaml` to status: integrated, "
                        "preserve its source engagement, and bind it to the source debt and final "
                        "integration receipt with source_debt_sha256 and "
                        "integration_receipt_sha256.",
                    ],
                },
            )
        raise ValueError(
            "defaults.score_shape must be one of: full-lifecycle, targeted-work, "
            "lifecycle-integration"
        )

    def _build_prelude(
        self,
        identity_dir: str,
        defaults: dict[str, Any],
    ) -> list[dict[str, object]]:
        """Build prelude injections (loaded for ALL sheets)."""
        prelude: list[dict[str, object]] = []

        # Agent L1 identity is always in prelude
        prelude.append(
            {
                "file": f"{identity_dir}/identity.md",
                "as": "context",
                "required": True,
            }
        )

        # Add any global prelude files from defaults
        for item in defaults.get("prelude", []):
            if isinstance(item, dict):
                prelude.append(item)

        return prelude

    def _build_cadenzas(
        self,
        identity_dir: str,
        defaults: dict[str, Any],
    ) -> dict[int, list[dict[str, object]]]:
        """Build per-sheet cadenza injections."""
        profile = {
            "file": f"{identity_dir}/profile.yaml",
            "as": "context",
            "required": True,
        }
        recent = {
            "file": f"{identity_dir}/recent.md",
            "as": "context",
            "required": True,
        }
        growth = {
            "file": f"{identity_dir}/growth.md",
            "as": "context",
            "required": True,
        }

        cadenzas: dict[int, list[dict[str, object]]] = {
            # Recon: profile + recent for orientation
            1: [profile, recent],
            # Plan: recent context
            2: [recent],
            # Work: recent for continuity
            3: [recent],
            # Play: growth for creative exploration
            6: [growth],
            # Inspect: profile for domain awareness
            7: [profile, recent],
            # AAR: recent for review
            8: [recent],
            # Consolidate: profile + recent for memory management
            9: [profile, recent],
            # Reflect: profile + growth for insight
            10: [profile, growth],
            # Resurrect: full identity load
            12: [profile, recent, growth],
        }

        # Add shared cadenza directories
        cadenza_config = defaults.get("cadenzas", {})
        active_dirs = cadenza_config.get("active", [])
        for item in active_dirs:
            if isinstance(item, dict):
                phases = item.get("phases", [])
                for sheet_num in range(1, SHEETS_PER_CYCLE + 1):
                    phase = SHEET_PHASE.get(sheet_num, "")
                    if phase in phases or "all" in phases:
                        if sheet_num not in cadenzas:
                            cadenzas[sheet_num] = []
                        cadenzas[sheet_num].append({
                            "directory": item["directory"],
                            "as": item.get("as", "context"),
                            "required": item.get("required", True),
                        })

        return cadenzas

    def _build_dependencies(self) -> dict[int, list[int]]:
        """Build sheet dependency DAG.

        Sequential phases have linear dependencies.
        Parallel phases depend on the previous sequential sheet.
        Post-parallel phases depend on all parallel phase sheets.
        """
        return {
            2: [1],       # plan depends on recon
            3: [2],       # work depends on plan
            4: [3],       # temperature check depends on work
            5: [4],       # integration depends on temperature check
            6: [4],       # play runs beside integration
            # Inspect reviews the INTEGRATED state, so it waits for
            # Integration (Pallas field, GH #462): dispatched together, the
            # inspection artifact was written before the merge it judged.
            7: [5],
            8: [5, 6, 7],  # AAR depends on all of phase 2
            9: [5, 6, 7],  # consolidate depends on all of phase 2
            # Reflect reads CONSOLIDATED memory and the profile has one
            # writer at a time (GH #464): Reflect waits for Consolidate.
            10: [9],
            11: [8, 9, 10],  # maturity check depends on all of phase 3
            12: [11],        # resurrect depends on maturity check
        }

    def _build_skip_when(
        self,
        agent_def: dict[str, Any],
        defaults: dict[str, Any],
        identity_dir: str,
    ) -> dict[int, dict[str, Any]]:
        """Build skip_when for conditional sheet execution.

        The temperature check (sheet 4) gates the play sheet (sheet 6).
        """
        play_routing = defaults.get("play_routing", {})
        if not play_routing:
            return {}

        name = agent_def["name"]
        memory_bloat = play_routing.get("memory_bloat_threshold", 3000)
        stagnation = play_routing.get("stagnation_cycles", 3)
        min_cycles = play_routing.get("min_cycles_between_play", 5)

        # Play is gated: skip play (sheet 6) if temperature check says work.
        # The temperature-check CLI sheet always exits 0 and writes one of
        # these markers; skip_when consumes the work marker.
        temp_cmd = (
            f"AGENT_DIR={shlex.quote(identity_dir)} AGENT_NAME={shlex.quote(name)} "
            f"MEMORY_BLOAT_THRESHOLD={memory_bloat} "
            f"STAGNATION_CYCLES={stagnation} "
            f"MIN_CYCLES_BETWEEN_PLAY={min_cycles} "
            f"test -f {{workspace}}/cycle-state/temperature-{name}-work"
        )

        return {
            6: {
                "command": temp_cmd,
                "description": "Skip play if temperature check says work",
                "timeout_seconds": 30,
            },
        }

    def get_phase_for_sheet(self, sheet_num: int) -> str:
        """Return the phase name for a given sheet number."""
        return SHEET_PHASE.get(sheet_num, "unknown")

    def get_sheets_for_phase(self, phase: str) -> list[int]:
        """Return sheet numbers for a given phase name."""
        return PHASE_MAP.get(phase, [])

    def is_cli_sheet(self, sheet_num: int) -> bool:
        """Return True if the sheet is a CLI instrument (not an LLM call)."""
        return sheet_num in CLI_SHEETS
