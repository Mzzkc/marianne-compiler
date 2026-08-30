"""12-phase prompt template emission (#211, #212).

The design spec (§3.3) requires every generated score to carry a
``prompt.template`` — a stage-conditional Jinja template that gives each
of the 12 cycle phases its invocation, references the score's
``stakes``/``thinking_method``/identity variables (previously emitted
but referenced by nothing), and embeds the per-phase technique manifests
the TechniqueWirer generates (previously generated and silently
dropped — #212).

The per-phase bodies are deliberately compact: identity depth comes from
the prelude/cadenza injections (identity.md, profile.yaml, technique
docs); the template's job is orientation — which phase this is, what the
phase is FOR, and which techniques are live.
"""

from __future__ import annotations

from marianne_compiler.sheets import SHEET_PHASE, SHEETS_PER_CYCLE

# One-line objective per cycle phase. Sheet numbers map via
# sheets.PHASE_MAP; CLI sheets (4, 11) are checks executed by command
# instruments and get minimal bodies.
PHASE_OBJECTIVES: dict[str, str] = {
    "recon": "Survey the terrain: what exists, what changed since last "
    "cycle, what raw material and open threads are available.",
    "plan": "Turn recon into a concrete, falsifiable plan for THIS cycle: "
    "scoped goals, file-level targets, success criteria.",
    "work": "Execute the plan. Build, write, fix. Leave the workspace "
    "better and the plan's success criteria satisfied.",
    "temperature_check": "Automated mid-cycle health check.",
    "integration": "Integrate the work: reconcile with the wider system, "
    "resolve seams, make it land cleanly.",
    "play": "Free exploration: try the unexpected angle, prototype the "
    "weird idea, stress what was built.",
    "inspect": "Adversarial review of the cycle's work: find what is "
    "wrong, weak, or missing. No politeness.",
    "aar": "After-action review: what happened vs what was intended, "
    "and why. Specific, falsifiable observations.",
    "consolidate": "Compress the cycle's learnings into durable artifacts: "
    "memory updates, distilled notes, pruned noise.",
    "reflect": "Step back: what does this cycle mean for the agent's "
    "trajectory and the project's direction?",
    "maturity_check": "Automated end-of-cycle maturity measurement.",
    "resurrect": "Prepare the next incarnation: write the handoff your "
    "successor needs to continue without you.",
}


def _exact_section_labels(*sections: str) -> str:
    labels = ", ".join(f"{section}:" for section in sections)
    return f"Use exact section labels: {labels}."


PHASE_OUTPUTS: dict[str, list[str]] = {
    "recon": [
        "Write `{{ workspace }}/cycle-state/{{ agent_name }}-recon.md`.",
        _exact_section_labels(
            "OBSERVED", "CHANGED", "CANDIDATES", "RISKS", "CONTEXT APPLIED", "EVIDENCE",
        ),
        "Under CONTEXT APPLIED, identify specific identity/memory/technique/cadenza "
        "material that affected present judgment; a roster name is not evidence of delivery.",
        "If you state a count of fleet agent scores, derive it from the current "
        "`{{ workspace }}/scores/*.yaml` files and do not estimate.",
    ],
    "plan": [
        "Write `{{ workspace }}/cycle-state/{{ agent_name }}-plan.md`.",
        _exact_section_labels(
            "CLAIMED WORK", "SUCCESS CRITERIA", "STEPS", "RISKS", "VALIDATION",
        ),
    ],
    "work": [
        "Execute only the scoped plan. Update project files as needed.",
        "Write `{{ workspace }}/cycle-state/{{ agent_name }}-work.md` "
        "with exact section labels: WORK DONE:, FILES CHANGED:, EVIDENCE:, NEXT:.",
    ],
    "temperature_check": [
        "This is a command-driven check. Do not substitute prose for the check result.",
    ],
    "integration": [
        "Write `{{ workspace }}/cycle-state/{{ agent_name }}-integration.md`.",
        _exact_section_labels("INTEGRATED", "CONFLICTS", "DECISIONS", "EVIDENCE"),
    ],
    "play": [
        "Create or update a play artifact under `{{ workspace }}/playspace/{{ agent_name }}/`.",
        "Write `{{ workspace }}/cycle-state/{{ agent_name }}-play.md` "
        "with exact section labels: EXPERIMENT:, RESULT:, TRANSFER:.",
    ],
    "inspect": [
        "Write `{{ workspace }}/cycle-state/{{ agent_name }}-inspection.md`.",
        _exact_section_labels("VERDICT", "EVIDENCE", "FAILURES", "RISKS", "REQUIRED FIXES"),
    ],
    "aar": [
        "Write `{{ workspace }}/cycle-state/{{ agent_name }}-aar.md`.",
        _exact_section_labels("INTENDED", "ACTUAL", "DELTA", "SUSTAIN", "IMPROVE", "EVIDENCE"),
    ],
    "consolidate": [
        "Update recent/profile memory files only with grounded facts from this cycle.",
        "Write `{{ workspace }}/cycle-state/{{ agent_name }}-consolidation.md` "
        "with exact section labels: BELIEFS:, PRUNED:, ARCHIVED:, EVIDENCE:.",
    ],
    "reflect": [
        "Update growth/profile relationship notes when warranted.",
        "Write `{{ workspace }}/cycle-state/{{ agent_name }}-reflection.md` "
        "with exact section labels: TRAJECTORY:, RELATIONSHIPS:, GROWTH:, NEXT:.",
    ],
    "maturity_check": [
        "This is a command-driven check. Do not substitute prose for the check result.",
    ],
    "resurrect": [
        "Update identity files only when the cycle evidence justifies it.",
        "Write `{{ workspace }}/cycle-state/{{ agent_name }}-resurrection.md` "
        "with exact section labels: IDENTITY CHANGES:, MEMORY STATE:, NEXT CYCLE:.",
    ],
}


def build_phase_template(
    technique_manifests: dict[int, str] | None = None,
) -> str:
    """Build the stage-conditional Jinja template for a generated score.

    Args:
        technique_manifests: Per-sheet technique manifest markdown from
            ``TechniqueWirer.wire()`` — embedded verbatim in the matching
            phase branch (#212). Sheets without manifests get no
            technique section.

    Returns:
        A Jinja template string with one branch per cycle sheet.
    """
    manifests = technique_manifests or {}
    branches: list[str] = []

    for sheet_num in range(1, SHEETS_PER_CYCLE + 1):
        phase = SHEET_PHASE.get(sheet_num, "work")
        if phase == "temperature_check":
            branches.append(_build_temperature_check_branch(sheet_num))
            continue
        if phase == "maturity_check":
            branches.append(_build_maturity_check_branch(sheet_num))
            continue

        objective = PHASE_OBJECTIVES.get(phase, "Do this phase's work.")
        keyword = "if" if sheet_num == 1 else "elif"

        lines = [
            f"{{% {keyword} stage == {sheet_num} %}}",
            f"# Phase: {phase} (sheet {sheet_num} of {SHEETS_PER_CYCLE})",
            "",
            "You are {{ agent_name }} — {{ role }}. Focus: {{ focus }}.",
            "Voice: {{ agent_voice }}",
            "",
            f"Objective: {objective}",
        ]

        outputs = PHASE_OUTPUTS.get(phase, [])
        if outputs:
            lines.extend(["", "## Required Output"])
            lines.extend(f"- {item}" for item in outputs)
            lines.extend([
                "- Do not claim completion unless the required artifact exists.",
                "- Ground claims in file paths, command output, or observed workspace state.",
                "- If shared active cadenza files are available in this phase, read "
                "all four direct files: `01-task-board.md`, `02-status.md`, "
                "`03-urgent-directives.md`, and `04-handoffs.md`. Treat urgent "
                "directives as controlling. Mark your owner-scoped task claim done "
                "with the required artifact as evidence; update `02-status.md` in "
                "its existing form without inventing a schema; add a handoff tuple "
                "when another owner must continue. If a second write conflict blocks "
                "a required update, "
                "write `COORDINATION UPDATE BLOCKED:` in the required artifact "
                "with the blocked file and reason.",
                "- If a shared active cadenza file changes while you edit it, "
                "re-read it and retry only your owner-scoped row once; after "
                "a second conflict, record the blocked coordination update in "
                "your required artifact and keep moving.",
            ])

        manifest = manifests.get(sheet_num, "").strip()
        if manifest:
            lines.extend(["", manifest])

        if phase == "recon":
            lines.extend([
                "",
                "{% if stakes %}## Stakes",
                "{{ stakes }}",
                "{% endif %}",
            ])
        if phase in ("plan", "inspect", "reflect"):
            lines.extend([
                "",
                "{% if thinking_method %}## Thinking method",
                "{{ thinking_method }}",
                "{% endif %}",
            ])

        lines.extend([
            "",
            "Workspace: {{ workspace }}",
            "Identity dir: {{ agent_identity_dir }}",
        ])

        branches.append("\n".join(lines))

    branches.append("{% endif %}")
    return "\n".join(branches) + "\n"


def _branch_keyword(sheet_num: int) -> str:
    return "if" if sheet_num == 1 else "elif"


def _build_temperature_check_branch(sheet_num: int) -> str:
    """Build the raw Bash command body for the temperature-check sheet."""
    keyword = _branch_keyword(sheet_num)
    return "\n".join(
        [
            f"{{% {keyword} stage == {sheet_num} %}}",
            "set -euo pipefail",
            'WORKSPACE="{{ workspace }}"',
            'AGENT_DIR="{{ agent_identity_dir }}"',
            'AGENT_NAME="{{ agent_name }}"',
            'STATE_DIR="${WORKSPACE}/cycle-state"',
            'mkdir -p "$STATE_DIR"',
            'rm -f "$STATE_DIR/temperature-${AGENT_NAME}-play"',
            'rm -f "$STATE_DIR/temperature-${AGENT_NAME}-work"',
            'THRESHOLD="${MEMORY_BLOAT_THRESHOLD:-3000}"',
            'STAGNATION="${STAGNATION_CYCLES:-3}"',
            'MIN_BETWEEN="${MIN_CYCLES_BETWEEN_PLAY:-5}"',
            "",
            _profile_assignment("cycle_count", "cycle_count"),
            _profile_assignment("last_play", "last_play_cycle"),
            'cycle_count="${cycle_count:-0}"',
            'last_play="${last_play:-0}"',
            'case "$cycle_count" in ""|*[!0-9-]*) cycle_count=0 ;; esac',
            'case "$last_play" in ""|*[!0-9-]*) last_play=0 ;; esac',
            "",
            'decision="work"',
            'reason="default-work"',
            'since_play=$((cycle_count - last_play))',
            'if [ "$since_play" -lt "$MIN_BETWEEN" ]; then',
            '  reason="too-soon-since-play"',
            "else",
            '  l3_words="$(wc -w < "$AGENT_DIR/recent.md" 2>/dev/null || echo 0)"',
            '  l3_words="$(echo "$l3_words" | tr -d "[:space:]")"',
            '  l3_words="${l3_words:-0}"',
            '  if [ "$l3_words" -gt "$THRESHOLD" ]; then',
            '    decision="play"',
            '    reason="memory-bloat"',
            '  elif [ -f "$AGENT_DIR/growth.md" ]; then',
            '    growth_mtime="$(stat -c %Y "$AGENT_DIR/growth.md" 2>/dev/null || echo 0)"',
            '    now="$(date +%s)"',
            '    growth_age_days=$(((now - growth_mtime) / 86400))',
            '    growth_age_days="$(echo "$growth_age_days" | tr -d "[:space:]")"',
            '    growth_age_days="${growth_age_days:-0}"',
            '    if [ "$growth_age_days" -gt "$STAGNATION" ]; then',
            '      decision="play"',
            '      reason="growth-stagnation"',
            "    fi",
            "  fi",
            '  if [ "$decision" = "work" ] && [ -f "$WORKSPACE/TASKS.md" ]; then',
            '    urgent="$(grep -Ec "\\- \\[ \\].*(P0|P1)" \\',
            '      "$WORKSPACE/TASKS.md" 2>/dev/null || true)"',
            '    urgent="$(echo "$urgent" | tr -d "[:space:]")"',
            '    urgent="${urgent:-0}"',
            '    if [ "$urgent" -eq 0 ]; then',
            '      decision="play"',
            '      reason="no-urgent-tasks"',
            "    fi",
            "  fi",
            '  if [ "$decision" = "work" ] && [ -f "$WORKSPACE/composer-notes.yaml" ]; then',
            '    if grep -qi "play.*${AGENT_NAME}" "$WORKSPACE/composer-notes.yaml"; then',
            '      decision="play"',
            '      reason="composer-directive"',
            "    fi",
            "  fi",
            "fi",
            "",
            'if [ "$decision" = "play" ]; then',
            '  touch "$STATE_DIR/temperature-${AGENT_NAME}-play"',
            "else",
            '  touch "$STATE_DIR/temperature-${AGENT_NAME}-work"',
            "fi",
            'cat > "$STATE_DIR/temperature-${AGENT_NAME}-report.md" <<REPORT',
            'decision: ${decision}',
            'reason: ${reason}',
            'cycle_count: ${cycle_count}',
            'last_play_cycle: ${last_play}',
            'REPORT',
            'echo "temperature decision: ${decision} (${reason})"',
        ]
    )


def _build_maturity_check_branch(sheet_num: int) -> str:
    """Build the raw Bash command body for the maturity-check sheet."""
    keyword = _branch_keyword(sheet_num)
    return "\n".join(
        [
            f"{{% {keyword} stage == {sheet_num} %}}",
            "set -euo pipefail",
            'WORKSPACE="{{ workspace }}"',
            'AGENT_DIR="{{ agent_identity_dir }}"',
            'STATE_DIR="${WORKSPACE}/cycle-state"',
            'REPORT_PATH="${STATE_DIR}/{{ agent_name }}-maturity-report.yaml"',
            'mkdir -p "$STATE_DIR"',
            "",
            _profile_assignment(
                "current_stage",
                "developmental_stage",
                action='gsub(/^[ \\t]+|[ \\t]+$/, "", $2); print $2; exit',
            ),
            _profile_assignment("standing_patterns", "standing_pattern_count"),
            _profile_assignment("cycle_count", "cycle_count"),
            'current_stage="${current_stage:-recognition}"',
            'standing_patterns="${standing_patterns:-0}"',
            'cycle_count="${cycle_count:-0}"',
            'case "$standing_patterns" in ""|*[!0-9-]*) standing_patterns=0 ;; esac',
            'case "$cycle_count" in ""|*[!0-9-]*) cycle_count=0 ;; esac',
            'growth_entries="$(grep -c "^## " "$AGENT_DIR/growth.md" 2>/dev/null || true)"',
            'growth_entries="${growth_entries:-0}"',
            "",
            'suggested_stage="$current_stage"',
            'if [ "$current_stage" = "recognition" ] && [ "$cycle_count" -gt 10 ]; then',
            '  suggested_stage="integration"',
            'elif [ "$current_stage" = "integration" ] && [ "$standing_patterns" -gt 2 ]; then',
            '  suggested_stage="generation"',
            "fi",
            "",
            'cat > "$REPORT_PATH" <<REPORT',
            'current_stage: ${current_stage}',
            'suggested_stage: ${suggested_stage}',
            'standing_pattern_count: ${standing_patterns}',
            'growth_entry_count: ${growth_entries}',
            'cycle_count: ${cycle_count}',
            'assessed_at: "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"',
            'REPORT',
            'echo "maturity stage: ${current_stage} (suggested: ${suggested_stage})"',
        ]
    )


def _profile_assignment(
    variable: str,
    field: str,
    *,
    action: str = 'gsub(/ /, "", $2); print $2; exit',
) -> str:
    """Return a shell assignment that reads one top-level YAML scalar."""
    return (
        f'{variable}="$(awk -F: '
        f'\'$1 == "{field}" {{{action}}}\' '
        '"$AGENT_DIR/profile.yaml" 2>/dev/null || true)"'
    )


__all__ = ["PHASE_OBJECTIVES", "build_phase_template"]
