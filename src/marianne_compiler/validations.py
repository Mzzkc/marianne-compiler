"""Validation generator — produces per-sheet validation rules.

Generates validation rules based on the agent lifecycle phases:
- Recon: report file exists
- Plan: plan file exists
- Work: user-defined test commands (TDD)
- Inspect: inspection report exists, user-defined coverage checks
- AAR: SUSTAIN/IMPROVE sections present
- CLI instruments: temperature check, maturity check, token budget
- Resurrect: token budget check

All validations use stage-based conditional execution so they only
fire on the appropriate sheet. Paths use ``{workspace}`` format syntax
(Python str.format), NOT Jinja2 ``{{workspace}}``.
"""

from __future__ import annotations

import logging
from typing import Any

from marianne_compiler.sheets import SHEET_PHASE, SHEETS_PER_CYCLE

_logger = logging.getLogger(__name__)


class ValidationGenerator:
    """Generates per-sheet validation rules for agent scores.

    Produces structural validations (file exists, content checks),
    CLI instrument validations (temperature/maturity/budget checks),
    and allows injection of custom validations from the compiler config.
    """

    def generate(
        self,
        agent_def: dict[str, Any],
        defaults: dict[str, Any],
        *,
        agents_dir: str = "",
        instruments_dir: str = "",
    ) -> list[dict[str, Any]]:
        """Generate validation rules for an agent score.

        Args:
            agent_def: Agent definition dict.
            defaults: Global defaults from compiler config.
            agents_dir: Path to agents identity directory.
            instruments_dir: Path to shared instruments directory.

        Returns:
            List of validation rule dicts for the score YAML.
        """
        name = agent_def["name"]
        validations: list[dict[str, Any]] = []
        cadenza_completion_phases = self._cadenza_completion_phases(defaults)

        # Recon report
        recon_path = f"{{workspace}}/cycle-state/{name}-recon.md"
        validations.extend(self._artifact_validations(
            path=recon_path,
            stage=1,
            description=f"Recon report for {name}",
            min_words=80,
            required_sections=["OBSERVED", "CHANGED", "CANDIDATES", "RISKS", "EVIDENCE"],
        ))
        if "recon" in cadenza_completion_phases:
            validations.append(
                self._cadenza_completion_validation(name, "recon", 1, recon_path)
            )
        if defaults.get("fleet_score_count_truth_check"):
            validations.append(self._fleet_score_count_validation(name))

        # Plan document
        plan_path = f"{{workspace}}/cycle-state/{name}-plan.md"
        validations.extend(self._artifact_validations(
            path=plan_path,
            stage=2,
            description=f"Cycle plan for {name}",
            min_words=80,
            required_sections=["CLAIMED WORK", "SUCCESS CRITERIA", "STEPS", "RISKS", "VALIDATION"],
        ))
        if "plan" in cadenza_completion_phases:
            validations.append(
                self._cadenza_completion_validation(name, "plan", 2, plan_path)
            )

        # User-defined work validations (TDD — test commands etc.)
        for val in defaults.get("validations", []):
            if isinstance(val, dict):
                validations.append({
                    "type": "command_succeeds",
                    "command": val["command"],
                    "condition": "stage == 3",
                    "description": val.get("description", val["command"]),
                    "timeout_seconds": val.get("timeout_seconds", 600),
                })

        # Temperature check (CLI instrument, sheet 4)
        validations.append({
            "type": "command_succeeds",
            "command": (
                f'test -f "{{workspace}}/cycle-state/temperature-{name}-play" -o '
                f'-f "{{workspace}}/cycle-state/temperature-{name}-work"'
            ),
            "condition": "stage == 4",
            "description": f"Temperature routing marker for {name}",
            "timeout_seconds": 10,
        })
        if instruments_dir and agents_dir:
            validations.append({
                "type": "command_succeeds",
                "command": (
                    f"AGENT_DIR={agents_dir}/{name} "
                    f"bash {instruments_dir}/temperature-check.sh"
                ),
                "condition": "stage == 4",
                "description": f"Temperature check for {name}",
                "timeout_seconds": 30,
            })

        # Work report
        work_path = f"{{workspace}}/cycle-state/{name}-work.md"
        validations.extend(self._artifact_validations(
            path=work_path,
            stage=3,
            description=f"Work report for {name}",
            min_words=60,
            required_sections=["WORK DONE", "FILES CHANGED", "EVIDENCE", "NEXT"],
        ))
        if "work" in cadenza_completion_phases:
            validations.append(
                self._cadenza_completion_validation(name, "work", 3, work_path)
            )

        # Integration report
        integration_path = f"{{workspace}}/cycle-state/{name}-integration.md"
        validations.extend(self._artifact_validations(
            path=integration_path,
            stage=5,
            description=f"Integration report for {name}",
            min_words=60,
            required_sections=["INTEGRATED", "CONFLICTS", "DECISIONS", "EVIDENCE"],
        ))
        if "integration" in cadenza_completion_phases:
            validations.append(
                self._cadenza_completion_validation(
                    name, "integration", 5, integration_path
                )
            )

        # Play report
        play_path = f"{{workspace}}/cycle-state/{name}-play.md"
        validations.extend(self._artifact_validations(
            path=play_path,
            stage=6,
            description=f"Play report for {name}",
            min_words=40,
            required_sections=["EXPERIMENT", "RESULT", "TRANSFER"],
        ))
        if "play" in cadenza_completion_phases:
            validations.append(
                self._cadenza_completion_validation(name, "play", 6, play_path)
            )

        # Inspection report
        inspection_path = f"{{workspace}}/cycle-state/{name}-inspection.md"
        validations.extend(self._artifact_validations(
            path=inspection_path,
            stage=7,
            description=f"Inspection report for {name}",
            min_words=80,
            required_sections=["VERDICT", "EVIDENCE", "FAILURES", "RISKS", "REQUIRED FIXES"],
        ))
        if "inspect" in cadenza_completion_phases:
            validations.append(
                self._cadenza_completion_validation(
                    name, "inspect", 7, inspection_path
                )
            )

        # User-defined coverage validations (applied to inspect sheets)
        for cov_val in defaults.get("coverage_validations", []):
            if isinstance(cov_val, dict):
                validations.append({
                    "type": "command_succeeds",
                    "command": cov_val["command"],
                    "condition": "stage == 7",
                    "description": cov_val.get("description", cov_val["command"]),
                    "timeout_seconds": cov_val.get("timeout_seconds", 600),
                })

        # AAR structure
        aar_path = f"{{workspace}}/cycle-state/{name}-aar.md"
        validations.extend(self._artifact_validations(
            path=aar_path,
            stage=8,
            description=f"AAR for {name}",
            min_words=80,
            required_sections=["INTENDED", "ACTUAL", "DELTA", "SUSTAIN", "IMPROVE", "EVIDENCE"],
        ))
        if "aar" in cadenza_completion_phases:
            validations.append(
                self._cadenza_completion_validation(name, "aar", 8, aar_path)
            )

        # Memory and reflection reports
        consolidation_path = f"{{workspace}}/cycle-state/{name}-consolidation.md"
        validations.extend(self._artifact_validations(
            path=consolidation_path,
            stage=9,
            description=f"Consolidation report for {name}",
            min_words=60,
            required_sections=["BELIEFS", "PRUNED", "ARCHIVED", "EVIDENCE"],
        ))
        if "consolidate" in cadenza_completion_phases:
            validations.append(
                self._cadenza_completion_validation(
                    name, "consolidate", 9, consolidation_path
                )
            )
        reflection_path = f"{{workspace}}/cycle-state/{name}-reflection.md"
        validations.extend(self._artifact_validations(
            path=reflection_path,
            stage=10,
            description=f"Reflection report for {name}",
            min_words=60,
            required_sections=["TRAJECTORY", "RELATIONSHIPS", "GROWTH", "NEXT"],
        ))
        if "reflect" in cadenza_completion_phases:
            validations.append(
                self._cadenza_completion_validation(name, "reflect", 10, reflection_path)
            )

        # Maturity check (CLI instrument, sheet 11)
        validations.append({
            "type": "file_exists",
            "path": f"{{workspace}}/cycle-state/{name}-maturity-report.yaml",
            "condition": "stage == 11",
            "description": f"Maturity report for {name}",
        })
        if instruments_dir and agents_dir:
            validations.append({
                "type": "command_succeeds",
                "command": (
                    f"AGENT_DIR={agents_dir}/{name} "
                    f"REPORT_PATH={{workspace}}/cycle-state/maturity-report.yaml "
                    f"bash {instruments_dir}/maturity-check.sh"
                ),
                "condition": "stage == 11",
                "description": f"Maturity check for {name}",
                "timeout_seconds": 30,
            })

        # Token budget check on resurrect (sheet 12)
        if instruments_dir and agents_dir:
            validations.append({
                "type": "command_succeeds",
                "command": (
                    f"AGENT_DIR={agents_dir}/{name} "
                    f"L1_BUDGET=900 L2_BUDGET=1500 L3_BUDGET=1500 "
                    f"bash {instruments_dir}/token-budget-check.sh"
                ),
                "condition": "stage == 12",
                "description": f"Token budget for {name}",
                "timeout_seconds": 10,
            })

        resurrection_path = f"{{workspace}}/cycle-state/{name}-resurrection.md"
        validations.extend(self._artifact_validations(
            path=resurrection_path,
            stage=12,
            description=f"Resurrection report for {name}",
            min_words=50,
            required_sections=["IDENTITY CHANGES", "MEMORY STATE", "NEXT CYCLE"],
        ))
        if "resurrect" in cadenza_completion_phases:
            validations.append(
                self._cadenza_completion_validation(
                    name, "resurrect", 12, resurrection_path
                )
            )

        # Custom user-defined validations from agent config
        for custom in agent_def.get("validations", []):
            if isinstance(custom, dict):
                validations.append(custom)

        return validations

    def _artifact_validations(
        self,
        *,
        path: str,
        stage: int,
        description: str,
        min_words: int,
        required_sections: list[str],
    ) -> list[dict[str, Any]]:
        """Build structural validations for an agent-authored artifact."""
        condition = f"stage == {stage}"
        validations: list[dict[str, Any]] = [
            {
                "type": "file_exists",
                "path": path,
                "condition": condition,
                "description": description,
            },
            {
                "type": "command_succeeds",
                "command": f'test "$(wc -w < "{path}")" -ge {min_words}',
                "condition": condition,
                "description": f"{description} has at least {min_words} words",
                "timeout_seconds": 10,
            },
        ]
        for section in required_sections:
            validations.append({
                "type": "content_contains",
                "path": path,
                "pattern": f"{section}:",
                "condition": condition,
                "description": f"{description} contains {section}",
            })
        return validations

    def _cadenza_completion_phases(self, defaults: dict[str, Any]) -> set[str]:
        """Return phases that must prove shared active cadenza completion."""
        if not defaults.get("cadenza_completion_validation"):
            return set()

        active = defaults.get("cadenzas", {}).get("active", [])
        phases: set[str] = set()
        for item in active:
            if not isinstance(item, dict):
                continue
            raw_phases = item.get("phases", [])
            if not isinstance(raw_phases, list):
                continue
            if "all" in raw_phases:
                return set(SHEET_PHASE.values()) - {"temperature_check", "maturity_check"}
            phases.update(str(phase) for phase in raw_phases)
        return phases

    def _cadenza_completion_validation(
        self,
        agent_name: str,
        phase: str,
        stage: int,
        artifact_path: str,
    ) -> dict[str, Any]:
        """Validate terminal task/status cadenza rows for one phase.

        The command permits a documented conflict fallback only when the
        required artifact carries an explicit ``COORDINATION UPDATE BLOCKED:``
        marker naming the blocked shared active file.
        """
        artifact_rel = artifact_path.removeprefix("{workspace}/")
        command = (
            f'WORKSPACE="{{workspace}}" AGENT={agent_name!r} PHASE={phase!r} '
            f'ARTIFACT="{artifact_path}" ARTIFACT_REL={artifact_rel!r} '
            """python - <<'PY'
from datetime import UTC, datetime, timedelta
import os
import sys
from pathlib import Path

workspace = Path(os.environ["WORKSPACE"])
agent = os.environ["AGENT"].lower()
phase = os.environ["PHASE"].lower()
artifact = Path(os.environ["ARTIFACT"])
artifact_rel = os.environ["ARTIFACT_REL"]
artifact_name = Path(artifact_rel).name

task_board = workspace / "shared" / "active" / "01-task-board.md"
status_board = workspace / "shared" / "active" / "02-agent-status.md"
artifact_text = artifact.read_text(errors="replace") if artifact.exists() else ""

marker = "COORDINATION UPDATE BLOCKED:"

def blocked_for(filename: str) -> bool:
    return marker in artifact_text and filename in artifact_text

def rows(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    parsed: list[list[str]] = []
    for line in path.read_text(errors="replace").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip().strip("`") for cell in stripped.strip("|").split("|")]
        if not cells or cells[0].lower() in {"id", "agent", "---"}:
            continue
        if all(set(cell) <= {"-"} for cell in cells if cell):
            continue
        parsed.append(cells)
    return parsed

task_ok = False
for cells in rows(task_board):
    if len(cells) < 5:
        continue
    owner = cells[1].lower()
    state = cells[2].lower()
    evidence = cells[4]
    if owner == agent and state == "done" and (
        artifact_rel in evidence or artifact_name in evidence
    ):
        task_ok = True
        break

status_ok = False
status_updated = ""
for cells in rows(status_board):
    if len(cells) < 6:
        continue
    row_agent = cells[0].lower()
    row_phase = cells[1].lower()
    state = cells[2].lower()
    if row_agent == agent and row_phase == phase and state == "complete":
        status_ok = True
        status_updated = cells[5]
        break

errors: list[str] = []
if not task_ok and not blocked_for("01-task-board.md"):
    errors.append(
        f"missing done task-board row for {agent} {phase} with evidence {artifact_rel}"
    )
if not status_ok and not blocked_for("02-agent-status.md"):
    errors.append(f"missing complete agent-status row for {agent} {phase}")
if status_ok:
    try:
        updated_at = datetime.strptime(status_updated, "%Y-%m-%dT%H:%MZ").replace(
            tzinfo=UTC
        )
    except ValueError:
        errors.append(
            f"invalid UTC agent-status timestamp for {agent} {phase}: "
            f"{status_updated!r}; use date -u +%Y-%m-%dT%H:%MZ"
        )
    else:
        if updated_at > datetime.now(UTC) + timedelta(minutes=5):
            errors.append(
                f"agent-status timestamp for {agent} {phase} is in the future: "
                f"{status_updated}; use date -u +%Y-%m-%dT%H:%MZ"
            )

if errors:
    print("; ".join(errors), file=sys.stderr)
    sys.exit(1)
PY"""
        )
        return {
            "type": "command_succeeds",
            "command": command,
            "condition": f"stage == {stage}",
            "description": f"Cadenza completion state for {agent_name} {phase}",
            "timeout_seconds": 10,
        }

    def _fleet_score_count_validation(self, agent_name: str) -> dict[str, Any]:
        """Validate concrete fleet score-count claims against disk state.

        This is intentionally narrow: reports may omit counts, but if they
        claim a count for agent score files, that claim must match the
        current ``scores/*.yaml`` files excluding ``fleet.yaml``.
        """
        report_path = f"{{workspace}}/cycle-state/{agent_name}-recon.md"
        command = f"""WORKSPACE={{workspace}} REPORT={report_path} python - <<'PY'
import os
import re
import sys
from pathlib import Path

workspace = Path(os.environ["WORKSPACE"])
report = Path(os.environ["REPORT"])
actual = sum(
    1
    for path in (workspace / "scores").glob("*.yaml")
    if path.name != "fleet.yaml"
)
text = report.read_text(errors="replace").lower()

units = {{
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}}
tens = {{
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
}}

def parse_count(raw: str) -> int | None:
    raw = raw.strip().replace("-", " ")
    if raw.isdigit():
        return int(raw)
    parts = raw.split()
    if len(parts) == 1:
        return units.get(parts[0]) or tens.get(parts[0])
    if len(parts) == 2 and parts[0] in tens and parts[1] in units:
        return tens[parts[0]] + units[parts[1]]
    return None

num = (
    r"\\d+|(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
    r"eighteen|nineteen|twenty|thirty|forty|fifty|sixty)"
    r"(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?"
)
claim_patterns = [
    re.compile(rf"\\b(?P<num>{{num}})\\s+(?:agent\\s+scores?|scored\\s+agents?|agent\\s+score\\s+files?)\\b"),
    re.compile(rf"\\b(?:agent\\s+scores?|scored\\s+agents?|agent\\s+score\\s+files?)\\D{{0,24}}(?P<num>{{num}})\\b"),
]
bad: list[tuple[str, int]] = []
for pattern in claim_patterns:
    for match in pattern.finditer(text):
        parsed = parse_count(match.group("num"))
        if parsed is not None and parsed != actual:
            bad.append((match.group(0), parsed))

if bad:
    print(
        f"fleet score count claim(s) disagree with disk count {{actual}}: "
        + "; ".join(f"{{claim!r}} -> {{count}}" for claim, count in bad),
        file=sys.stderr,
    )
    sys.exit(1)
PY"""
        return {
            "type": "command_succeeds",
            "command": command,
            "condition": "stage == 1",
            "description": f"Recon score-count claims match disk for {agent_name}",
            "timeout_seconds": 10,
        }

    def generate_structural(
        self,
        agent_name: str,
        phase: str,
    ) -> list[dict[str, Any]]:
        """Generate structural validations for a specific phase.

        Used when building validations for a single phase rather than
        the full lifecycle. Returns rules appropriate for the phase.
        """
        # Find the sheet number(s) for this phase
        sheet_nums: list[int] = []
        for snum in range(1, SHEETS_PER_CYCLE + 1):
            if SHEET_PHASE.get(snum) == phase:
                sheet_nums.append(snum)

        if not sheet_nums:
            return []

        validations: list[dict[str, Any]] = []
        stage = sheet_nums[0]

        if phase == "recon":
            validations.append({
                "type": "file_exists",
                "path": f"{{workspace}}/cycle-state/{agent_name}-recon.md",
                "condition": f"stage == {stage}",
                "description": "Recon report exists",
            })
        elif phase == "plan":
            validations.append({
                "type": "file_exists",
                "path": f"{{workspace}}/cycle-state/{agent_name}-plan.md",
                "condition": f"stage == {stage}",
                "description": "Cycle plan exists",
            })
        elif phase == "inspect":
            validations.append({
                "type": "file_exists",
                "path": f"{{workspace}}/cycle-state/{agent_name}-inspection.md",
                "condition": f"stage == {stage}",
                "description": "Inspection report exists",
            })
        elif phase == "aar":
            validations.append({
                "type": "content_contains",
                "path": f"{{workspace}}/cycle-state/{agent_name}-aar.md",
                "pattern": "SUSTAIN:",
                "condition": f"stage == {stage}",
                "description": "AAR has SUSTAIN",
            })
            validations.append({
                "type": "content_contains",
                "path": f"{{workspace}}/cycle-state/{agent_name}-aar.md",
                "pattern": "IMPROVE:",
                "condition": f"stage == {stage}",
                "description": "AAR has IMPROVE",
            })

        return validations
