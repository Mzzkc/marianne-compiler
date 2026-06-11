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
        objective = PHASE_OBJECTIVES.get(phase, "Do this phase's work.")
        keyword = "if" if sheet_num == 1 else "elif"

        lines = [
            f"{{% {keyword} stage == {sheet_num} %}}",
            f"# Phase: {phase} (sheet {sheet_num} of {SHEETS_PER_CYCLE})",
            "",
            "You are {{ agent_name }} — {{ role }}. Focus: {{ focus }}.",
            "Voice: {{ voice }}",
            "",
            f"Objective: {objective}",
        ]

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


__all__ = ["PHASE_OBJECTIVES", "build_phase_template"]
