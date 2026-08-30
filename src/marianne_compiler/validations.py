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
import shlex
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
            required_sections=[
                "OBSERVED",
                "CHANGED",
                "CANDIDATES",
                "RISKS",
                "CONTEXT APPLIED",
                "EVIDENCE",
            ],
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
                    f"AGENT_DIR={shlex.quote(f'{agents_dir}/{name}')} "
                    f"bash {shlex.quote(f'{instruments_dir}/temperature-check.sh')}"
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
        if defaults.get("score_shape") == "targeted-work" and agents_dir:
            validations.extend(
                self._targeted_debt_validations(name, agents_dir)
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
                    f"AGENT_DIR={shlex.quote(f'{agents_dir}/{name}')} "
                    f"REPORT_PATH={{workspace}}/cycle-state/maturity-report.yaml "
                    f"bash {shlex.quote(f'{instruments_dir}/maturity-check.sh')}"
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
                    f"AGENT_DIR={shlex.quote(f'{agents_dir}/{name}')} "
                    f"L1_BUDGET=900 L2_BUDGET=1500 L3_BUDGET=1500 "
                    f"bash {shlex.quote(f'{instruments_dir}/token-budget-check.sh')}"
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
        if defaults.get("score_shape") == "lifecycle-integration" and agents_dir:
            validations.extend(
                self._lifecycle_integration_validations(name, agents_dir)
            )

        # Custom user-defined validations from agent config
        for custom in agent_def.get("validations", []):
            if isinstance(custom, dict):
                validations.append(custom)

        return validations

    def _targeted_debt_validations(
        self,
        agent_name: str,
        agents_dir: str,
    ) -> list[dict[str, Any]]:
        debt_path = f"{agents_dir}/{agent_name}/.marianne/pending-lifecycle-debt.yaml"
        recent_path = f"{agents_dir}/{agent_name}/recent.md"
        snapshot_path = (
            f"{{workspace}}/cycle-state/{agent_name}-recent-before-targeted.md"
        )
        snapshot_command = (
            f"RECENT={shlex.quote(recent_path)} SNAPSHOT={snapshot_path} "
            """python - <<'PY'
import os
from pathlib import Path

source = Path(os.environ["RECENT"]).read_bytes()
snapshot = Path(os.environ["SNAPSHOT"])
snapshot.parent.mkdir(parents=True, exist_ok=True)
if snapshot.exists():
    if snapshot.read_bytes() != source:
        raise SystemExit("targeted memory snapshot already exists with different bytes")
else:
    fd = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(source)
PY"""
        )
        command = (
            f"DEBT={shlex.quote(debt_path)} RECENT={shlex.quote(recent_path)} "
            f"SNAPSHOT={snapshot_path} WORKSPACE={{workspace}} "
            f"AGENT={shlex.quote(agent_name)} "
            """python - <<'PY'
import hashlib
import os
from pathlib import Path

import yaml

debt = yaml.safe_load(Path(os.environ["DEBT"]).read_text())
if not isinstance(debt, dict):
    raise SystemExit("lifecycle debt must be a YAML mapping")
if debt.get("schema_version") != 1 or debt.get("kind") != "marianne-lifecycle-debt":
    raise SystemExit("lifecycle debt schema/kind mismatch")
if str(debt.get("agent", "")).lower() != os.environ["AGENT"].lower():
    raise SystemExit("lifecycle debt agent mismatch")
if debt.get("status") != "pending":
    raise SystemExit("lifecycle debt status must remain pending")
pending = {str(value) for value in debt.get("pending_phases", [])}
if pending != {"consolidate", "reflect", "resurrect"}:
    raise SystemExit("lifecycle debt must name all deferred phases exactly")
if not debt.get("source_engagement"):
    raise SystemExit("lifecycle debt lacks source engagement/evidence")
before = str(debt.get("recent_memory_before_sha256", ""))
after = str(debt.get("recent_memory_after_sha256", ""))
valid_hash = lambda value: len(value) == 71 and value.startswith("sha256:") and all(
    char in "0123456789abcdef" for char in value[7:]
)
if not valid_hash(before) or not valid_hash(after):
    raise SystemExit("lifecycle debt lacks memory hashes")
if before == after:
    raise SystemExit("targeted engagement did not produce a memory transition")
snapshot = Path(os.environ["SNAPSHOT"])
snapshot_hash = "sha256:" + hashlib.sha256(snapshot.read_bytes()).hexdigest()
if debt.get("recent_memory_before_snapshot") != str(snapshot) or before != snapshot_hash:
    raise SystemExit("lifecycle debt before hash is not bound to the stage-1 snapshot")
current = "sha256:" + hashlib.sha256(Path(os.environ["RECENT"]).read_bytes()).hexdigest()
if current != after:
    raise SystemExit("lifecycle debt after hash does not match canonical recent memory")
evidence = debt.get("evidence")
if not isinstance(evidence, list) or not evidence:
    raise SystemExit("lifecycle debt evidence must be a non-empty list")
workspace = Path(os.environ["WORKSPACE"]).resolve()
for item in evidence:
    if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
        raise SystemExit("each lifecycle debt evidence item needs path and sha256")
    path = Path(str(item["path"]))
    path = path if path.is_absolute() else workspace / path
    path = path.resolve()
    try:
        path.relative_to(workspace)
    except ValueError as exc:
        raise SystemExit("lifecycle debt evidence must stay in the score workspace") from exc
    if not path.is_file():
        raise SystemExit("lifecycle debt evidence file is missing")
    digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    if item["sha256"] != digest:
        raise SystemExit("lifecycle debt evidence hash mismatch")
PY"""
        )
        return [
            {
                "type": "command_succeeds",
                "command": snapshot_command,
                "condition": "stage == 1",
                "description": f"Capture targeted memory baseline for {agent_name}",
                "timeout_seconds": 10,
            },
            {
                "type": "file_exists",
                "path": snapshot_path,
                "condition": "stage == 8",
                "description": f"Targeted memory baseline for {agent_name}",
            },
            {
                "type": "file_exists",
                "path": debt_path,
                "condition": "stage == 8",
                "description": f"Pending lifecycle debt for {agent_name}",
            },
            {
                "type": "command_succeeds",
                "command": command,
                "condition": "stage == 8",
                "description": (
                    f"Targeted lifecycle debt for {agent_name} is grounded"
                ),
                "timeout_seconds": 10,
            },
        ]

    def _lifecycle_integration_validations(
        self,
        agent_name: str,
        agents_dir: str,
    ) -> list[dict[str, Any]]:
        metadata_path = f"{agents_dir}/{agent_name}/.marianne"
        debt_path = f"{metadata_path}/pending-lifecycle-debt.yaml"
        conflict_path = f"{metadata_path}/pending-seed-conflicts.yaml"
        input_path = (
            f"{{workspace}}/cycle-state/{agent_name}-lifecycle-inputs.yaml"
        )
        debt_snapshot_path = (
            f"{{workspace}}/cycle-state/{agent_name}-source-lifecycle-debt.yaml"
        )
        conflict_snapshot_path = (
            f"{{workspace}}/cycle-state/{agent_name}-source-seed-conflicts.yaml"
        )
        receipt_path = (
            f"{{workspace}}/cycle-state/{agent_name}-lifecycle-integration-receipt.yaml"
        )
        recent_path = f"{agents_dir}/{agent_name}/recent.md"
        snapshot_command = (
            f"DEBT={shlex.quote(debt_path)} CONFLICT={shlex.quote(conflict_path)} "
            f"INPUT={input_path} DEBT_SNAPSHOT={debt_snapshot_path} "
            f"CONFLICT_SNAPSHOT={conflict_snapshot_path} AGENT={shlex.quote(agent_name)} "
            """python - <<'PY'
import hashlib
import os
from pathlib import Path

import yaml

def digest(value):
    return "sha256:" + hashlib.sha256(value).hexdigest()

def preserve(source, target):
    value = source.read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != value:
            raise SystemExit(f"lifecycle input snapshot changed: {target}")
    else:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(value)
    return digest(value)

debt = Path(os.environ["DEBT"])
if not debt.is_file():
    raise SystemExit("lifecycle integration requires pending lifecycle debt")
debt_snapshot = Path(os.environ["DEBT_SNAPSHOT"])
document = {
    "schema_version": 1,
    "kind": "marianne-lifecycle-integration-inputs",
    "agent": os.environ["AGENT"],
    "source_debt_path": str(debt_snapshot),
    "source_debt_sha256": preserve(debt, debt_snapshot),
    "source_seed_conflicts_path": None,
    "source_seed_conflicts_sha256": None,
}
conflict = Path(os.environ["CONFLICT"])
if conflict.is_file():
    conflict_snapshot = Path(os.environ["CONFLICT_SNAPSHOT"])
    document["source_seed_conflicts_path"] = str(conflict_snapshot)
    document["source_seed_conflicts_sha256"] = preserve(conflict, conflict_snapshot)
target = Path(os.environ["INPUT"])
rendered = yaml.safe_dump(document, sort_keys=False).encode()
if target.exists() and target.read_bytes() != rendered:
    raise SystemExit("lifecycle input manifest already exists with different bytes")
if not target.exists():
    target.write_bytes(rendered)
PY"""
        )
        command = (
            f"RECEIPT={receipt_path} RECENT={shlex.quote(recent_path)} "
            f"DEBT={shlex.quote(debt_path)} INPUT={input_path} "
            f"AGENT_DIR={shlex.quote(f'{agents_dir}/{agent_name}')} "
            f"AGENT={shlex.quote(agent_name)} "
            """python - <<'PY'
import hashlib
import os
from pathlib import Path

import yaml

receipt = yaml.safe_load(Path(os.environ["RECEIPT"]).read_text())
if not isinstance(receipt, dict):
    raise SystemExit("lifecycle integration receipt must be a YAML mapping")
if receipt.get("schema_version") != 1 or receipt.get("kind") != "marianne-lifecycle-integration":
    raise SystemExit("lifecycle integration receipt schema/kind mismatch")
if str(receipt.get("agent", "")).lower() != os.environ["AGENT"].lower():
    raise SystemExit("lifecycle integration receipt agent mismatch")
if receipt.get("status") != "integrated":
    raise SystemExit("lifecycle integration status must be integrated")
inputs = yaml.safe_load(Path(os.environ["INPUT"]).read_text())
source_debt_path = Path(inputs["source_debt_path"])
source_debt_bytes = source_debt_path.read_bytes()
source_debt_hash = "sha256:" + hashlib.sha256(source_debt_bytes).hexdigest()
if source_debt_hash != inputs.get("source_debt_sha256"):
    raise SystemExit("source debt snapshot hash mismatch")
source_debt = yaml.safe_load(source_debt_bytes)
if receipt.get("source_debt_sha256") != source_debt_hash:
    raise SystemExit("integration receipt is not bound to source debt")
if receipt.get("source_memory") != "recent.md":
    raise SystemExit("integration source_memory must be canonical recent.md")
before = str(receipt.get("memory_before_sha256", ""))
after = str(receipt.get("memory_after_sha256", ""))
valid_hash = lambda value: len(value) == 71 and value.startswith("sha256:") and all(
    char in "0123456789abcdef" for char in value[7:]
)
if not valid_hash(before) or not valid_hash(after):
    raise SystemExit("lifecycle integration receipt lacks memory hashes")
if before != source_debt.get("recent_memory_after_sha256"):
    raise SystemExit("integration before hash does not continue source debt")
if before == after:
    raise SystemExit("lifecycle integration did not change canonical memory")
current = "sha256:" + hashlib.sha256(Path(os.environ["RECENT"]).read_bytes()).hexdigest()
if current != after:
    raise SystemExit("integration after hash does not match canonical recent memory")
if receipt.get("closed_debt") != [source_debt.get("source_engagement")]:
    raise SystemExit("closed_debt does not exactly name the source engagement")
recall = receipt.get("later_recall")
required_recall = {
    "source_engagement", "source_evidence_sha256", "recalled_learning", "present_application"
}
if not isinstance(recall, dict) or set(recall) != required_recall:
    raise SystemExit("later_recall must use the typed recall contract")
if recall["source_engagement"] != source_debt.get("source_engagement"):
    raise SystemExit("later recall source engagement mismatch")
evidence_hashes = {
    item.get("sha256") for item in source_debt.get("evidence", []) if isinstance(item, dict)
}
if recall["source_evidence_sha256"] not in evidence_hashes:
    raise SystemExit("later recall is not bound to source evidence")
if not str(recall["recalled_learning"]).strip() or not str(recall["present_application"]).strip():
    raise SystemExit("later recall lacks learning or present application")
receipt_hash = "sha256:" + hashlib.sha256(Path(os.environ["RECEIPT"]).read_bytes()).hexdigest()
debt = yaml.safe_load(Path(os.environ["DEBT"]).read_text())
if debt.get("status") != "integrated":
    raise SystemExit("canonical lifecycle debt was not closed")
if debt.get("source_debt_sha256") != source_debt_hash:
    raise SystemExit("closed lifecycle debt is not bound to its source")
if debt.get("integration_receipt_sha256") != receipt_hash:
    raise SystemExit("closed lifecycle debt is not bound to this integration receipt")
conflict_hash = inputs.get("source_seed_conflicts_sha256")
resolution_value = receipt.get("seed_resolution_receipt")
if conflict_hash:
    if not isinstance(resolution_value, str) or not resolution_value:
        raise SystemExit("seed conflict snapshot requires an agent resolution receipt")
    resolution_path = Path(resolution_value).resolve()
    expected_root = (
        Path(os.environ["AGENT_DIR"]) / ".marianne" / "seed-resolution-receipts"
    ).resolve()
    try:
        resolution_path.relative_to(expected_root)
    except ValueError as exc:
        raise SystemExit("seed resolution receipt is outside agent-owned receipt storage") from exc
    resolution = yaml.safe_load(resolution_path.read_text())
    if (
        resolution.get("authority") != "agent"
        or resolution.get("pending_conflicts_sha256") != conflict_hash
    ):
        raise SystemExit("seed resolution receipt does not close observed conflicts")
elif resolution_value not in (None, ""):
    raise SystemExit("seed resolution receipt supplied without observed conflicts")
PY"""
        )
        return [
            {
                "type": "command_succeeds",
                "command": snapshot_command,
                "condition": "stage == 1",
                "description": f"Capture lifecycle inputs for {agent_name}",
                "timeout_seconds": 10,
            },
            {
                "type": "file_exists",
                "path": input_path,
                "condition": "stage == 12",
                "description": f"Lifecycle input manifest for {agent_name}",
            },
            {
                "type": "file_exists",
                "path": receipt_path,
                "condition": "stage == 12",
                "description": f"Lifecycle integration receipt for {agent_name}",
            },
            {
                "type": "command_succeeds",
                "command": command,
                "condition": "stage == 12",
                "description": (
                    f"Lifecycle integration recall for {agent_name} is grounded"
                ),
                "timeout_seconds": 10,
            },
        ]

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
        """Validate the canonical four-file cadenza without inventing schemas.

        The command permits a documented conflict fallback only when the
        required artifact carries an explicit ``COORDINATION UPDATE BLOCKED:``
        marker naming the blocked shared active file.
        """
        artifact_rel = artifact_path.removeprefix("{workspace}/")
        command = (
            f'WORKSPACE="{{workspace}}" AGENT={agent_name!r} PHASE={phase!r} '
            f'ARTIFACT="{artifact_path}" ARTIFACT_REL={artifact_rel!r} '
            """python - <<'PY'
import os
import re
import sys
from pathlib import Path

workspace = Path(os.environ["WORKSPACE"])
agent = os.environ["AGENT"].lower()
phase = os.environ["PHASE"].lower()
artifact = Path(os.environ["ARTIFACT"])
artifact_rel = os.environ["ARTIFACT_REL"]
artifact_name = Path(artifact_rel).name

task_board = workspace / "shared" / "active" / "01-task-board.md"
status_board = workspace / "shared" / "active" / "02-status.md"
directives = workspace / "shared" / "active" / "03-urgent-directives.md"
handoffs = workspace / "shared" / "active" / "04-handoffs.md"
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

def task_id_errors() -> list[str]:
    errors: list[str] = []
    seen: dict[str, int] = {}
    for cells in rows(task_board):
        if not cells:
            continue
        row_id = cells[0]
        if not row_id or "{" in row_id or "}" in row_id:
            continue
        seen[row_id] = seen.get(row_id, 0) + 1
        if re.fullmatch(r"(?:[A-Z]+-)?\\d+", row_id):
            errors.append(
                f"01-task-board.md uses global numeric cadenza id {row_id!r}; "
                "use an owner-scoped id such as agent-T-001"
            )
    for row_id, count in seen.items():
        if count > 1:
            errors.append(
                f"01-task-board.md repeats concrete cadenza id {row_id!r} {count} times"
            )
    return errors

task_ok = False
for cells in rows(task_board):
    lowered = [cell.lower() for cell in cells]
    owner_ok = agent in lowered
    state_ok = any(cell == "done" or cell.startswith("done ") for cell in lowered)
    evidence_ok = any(
        artifact_rel in cell or artifact_name in cell
        for cell in cells
    )
    if owner_ok and state_ok and evidence_ok:
        task_ok = True
        break

status_text = status_board.read_text(errors="replace") if status_board.exists() else ""
status_folded = status_text.lower()
status_ok = agent in status_folded and phase in status_folded and (
    artifact_rel in status_text or artifact_name in status_text
)

required_files = [task_board, status_board, directives, handoffs]
errors = [
    f"missing canonical active cadenza file {path.name}"
    for path in required_files
    if not path.is_file()
]
errors.extend(task_id_errors())
if not task_ok and not blocked_for("01-task-board.md"):
    errors.append(
        f"missing done task-board row for {agent} {phase} with evidence {artifact_rel}"
    )
if not status_ok and not blocked_for("02-status.md"):
    errors.append(
        f"02-status.md does not bind {agent} {phase} to evidence {artifact_rel}"
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
