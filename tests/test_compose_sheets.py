"""Tests for the sheet composer module."""

from __future__ import annotations

import subprocess
from pathlib import Path

from jinja2 import Environment

from marianne_compiler.prompt_template import build_phase_template
from marianne_compiler.sheets import (
    CLI_SHEETS,
    PHASE_MAP,
    SHEET_DESCRIPTIONS,
    SHEET_PHASE,
    SHEETS_PER_CYCLE,
    SheetComposer,
)


def _make_agent_def(name: str = "canyon") -> dict[str, object]:
    return {
        "name": name,
        "voice": "Structure persists.",
        "focus": "architecture",
    }


def _make_defaults() -> dict[str, object]:
    return {
        "play_routing": {
            "memory_bloat_threshold": 3000,
            "stagnation_cycles": 3,
            "min_cycles_between_play": 5,
        },
    }


class TestSheetComposer:
    """Tests for SheetComposer."""

    def test_produces_12_sheets(self) -> None:
        """Sheet composer produces a 12-sheet cycle."""
        composer = SheetComposer()
        result = composer.compose(_make_agent_def(), _make_defaults())

        assert result["total_items"] == 12
        assert result["size"] == 1

    def test_has_parallel_phase_dependencies(self) -> None:
        """Sheet config allows phases 2 and 3 to run in parallel via DAG."""
        composer = SheetComposer()
        result = composer.compose(_make_agent_def(), _make_defaults())

        assert "fan_out" not in result
        deps = result["dependencies"]
        assert deps[5] == [4]
        assert deps[6] == [4]
        assert deps[7] == [4]
        assert set(deps[8]) == {5, 6, 7}
        assert set(deps[9]) == {5, 6, 7}
        assert set(deps[10]) == {5, 6, 7}

    def test_has_dependencies(self) -> None:
        """Sheet config includes proper dependency DAG."""
        composer = SheetComposer()
        result = composer.compose(_make_agent_def(), _make_defaults())

        deps = result["dependencies"]
        # plan depends on recon
        assert deps[2] == [1]
        # work depends on plan
        assert deps[3] == [2]
        # phase 2 fan-out depends on temperature check
        assert deps[5] == [4]
        assert deps[6] == [4]
        assert deps[7] == [4]
        # phase 3 depends on all of phase 2
        assert set(deps[8]) == {5, 6, 7}
        # resurrect depends on maturity check
        assert deps[12] == [11]

    def test_has_prelude_with_identity(self) -> None:
        """Prelude includes the agent's L1 identity."""
        composer = SheetComposer()
        result = composer.compose(
            _make_agent_def(), _make_defaults(),
            agents_dir=Path("/test/agents"),
        )

        prelude = result["prelude"]
        assert any("identity.md" in p.get("file", "") for p in prelude)
        assert all(item.get("required") is True for item in prelude)

    def test_has_cadenzas_per_phase(self) -> None:
        """Cadenzas are defined for relevant phases."""
        composer = SheetComposer()
        result = composer.compose(_make_agent_def(), _make_defaults())

        cadenzas = result["cadenzas"]
        # Recon should have profile + recent
        assert 1 in cadenzas
        assert len(cadenzas[1]) >= 2
        # Resurrect should have full identity load
        assert 12 in cadenzas
        assert len(cadenzas[12]) >= 3
        assert all(
            item.get("required") is True
            for items in cadenzas.values()
            for item in items
        )

    def test_descriptions_for_all_sheets(self) -> None:
        """All 12 sheets have descriptions."""
        composer = SheetComposer()
        result = composer.compose(_make_agent_def(), _make_defaults())

        descriptions = result["descriptions"]
        for i in range(1, SHEETS_PER_CYCLE + 1):
            assert i in descriptions, f"Sheet {i} missing description"

    def test_skip_when_for_play(self) -> None:
        """Play sheet has skip_when gating."""
        composer = SheetComposer()
        result = composer.compose(_make_agent_def(), _make_defaults())

        skip = result.get("skip_when", {})
        assert 6 in skip  # Play sheet is gated
        assert "skip_when_command" not in result
        command = skip[6]["command"]
        assert "{workspace}" in command
        assert "{{workspace}}" not in command
        assert "temperature-play" not in command
        assert "temperature-canyon-work" in command

    def test_play_gate_only_affects_play(self) -> None:
        """Temperature check gates only Play, not Integration or Inspect."""
        composer = SheetComposer()
        result = composer.compose(_make_agent_def(), _make_defaults())

        skip = result.get("skip_when", {})
        # Play (sheet 6) is gated
        assert 6 in skip
        # Integration (sheet 5) and Inspect (sheet 7) are NOT gated
        assert 5 not in skip
        assert 7 not in skip

    def test_phase_map_coverage(self) -> None:
        """Phase map covers all 12 sheets."""
        all_sheets: set[int] = set()
        for sheets in PHASE_MAP.values():
            all_sheets.update(sheets)
        assert all_sheets == set(range(1, 13))

    def test_sheet_phase_reverse_map(self) -> None:
        """Sheet-to-phase reverse map covers all sheets."""
        for i in range(1, 13):
            assert i in SHEET_PHASE

    def test_cli_sheets(self) -> None:
        """CLI sheets are correctly identified."""
        assert 4 in CLI_SHEETS   # Temperature check
        assert 11 in CLI_SHEETS  # Maturity check
        assert 3 not in CLI_SHEETS  # Work is not CLI

    def test_sheet_descriptions_constant(self) -> None:
        """SHEET_DESCRIPTIONS covers all 12 sheets."""
        assert len(SHEET_DESCRIPTIONS) == 12
        for i in range(1, 13):
            assert i in SHEET_DESCRIPTIONS

    def test_get_phase_for_sheet(self) -> None:
        """get_phase_for_sheet returns correct phase names."""
        composer = SheetComposer()
        assert composer.get_phase_for_sheet(1) == "recon"
        assert composer.get_phase_for_sheet(3) == "work"
        assert composer.get_phase_for_sheet(6) == "play"
        assert composer.get_phase_for_sheet(12) == "resurrect"

    def test_is_cli_sheet(self) -> None:
        """is_cli_sheet correctly identifies CLI instrument sheets."""
        composer = SheetComposer()
        assert composer.is_cli_sheet(4)
        assert composer.is_cli_sheet(11)
        assert not composer.is_cli_sheet(3)
        assert not composer.is_cli_sheet(12)

    def test_no_play_routing_still_works(self) -> None:
        """Composer works without play routing config."""
        composer = SheetComposer()
        result = composer.compose(_make_agent_def(), {})

        assert result["total_items"] == 12
        # No skip_when when no play routing
        assert result.get("skip_when", {}) == {}


def _render_compiled_phase(
    *,
    sheet_num: int,
    workspace: Path,
    agent_dir: Path,
) -> str:
    template = Environment().from_string(build_phase_template())
    return template.render(
        stage=sheet_num,
        workspace=str(workspace),
        agent_identity_dir=str(agent_dir),
        agent_name="canyon",
        role="architect",
        focus="architecture",
        agent_voice="Structure persists.",
    )


class TestCompiledCliPhaseTemplates:
    """CLI phases render executable shell commands, not prose prompts."""

    def test_temperature_check_command_writes_play_marker(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        agent_dir = tmp_path / "agents" / "canyon"
        workspace.mkdir(parents=True)
        agent_dir.mkdir(parents=True)
        (workspace / "TASKS.md").write_text("- [x] Done (priority: P0)\n")
        (agent_dir / "profile.yaml").write_text(
            "cycle_count: 10\nlast_play_cycle: 0\n"
        )
        (agent_dir / "recent.md").write_text("short memory\n")
        (agent_dir / "growth.md").write_text("# Growth\n\n## Entry\n")

        command = _render_compiled_phase(
            sheet_num=4,
            workspace=workspace,
            agent_dir=agent_dir,
        )
        result = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert (workspace / "cycle-state" / "temperature-canyon-play").exists()
        assert not (workspace / "cycle-state" / "temperature-canyon-work").exists()
        assert "temperature decision: play" in result.stdout

    def test_maturity_check_command_writes_report(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        agent_dir = tmp_path / "agents" / "canyon"
        workspace.mkdir(parents=True)
        agent_dir.mkdir(parents=True)
        (agent_dir / "profile.yaml").write_text(
            "developmental_stage: recognition\n"
            "standing_pattern_count: 0\n"
            "cycle_count: 12\n"
        )
        (agent_dir / "growth.md").write_text("# Growth\n\n## Entry\n")

        command = _render_compiled_phase(
            sheet_num=11,
            workspace=workspace,
            agent_dir=agent_dir,
        )
        result = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            check=False,
        )

        report = workspace / "cycle-state" / "canyon-maturity-report.yaml"
        assert result.returncode == 0, result.stderr
        assert report.exists()
        assert "current_stage: recognition" in report.read_text()
