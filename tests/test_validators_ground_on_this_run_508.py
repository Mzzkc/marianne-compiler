"""Emitted validators must fail on absence, not pass on inherited artifacts (GH #508).

1. The score-count claim validator's second pattern was dead: inside the
   emitted rf-string, ``{0,24}`` was an f-expression rendering ``(0, 24)``, so
   ``agent scores total nine`` against a disk count of 0 was never caught.
2. The cadenza-completion validator accepted ANY done row whose evidence cell
   contained the artifact's relative path, so a row from an earlier engagement
   satisfied it before this run wrote anything.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from marianne_compiler.validations import ValidationGenerator


def _agent(name: str = "journey") -> dict[str, object]:
    return {"name": name, "voice": "v", "focus": "f"}


def _run(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", "-c", command], capture_output=True, text=True, timeout=20)


class TestScoreCountClaim:
    def _command(self, tmp_path: Path, report: str) -> str:
        ws = tmp_path / "run"
        (ws / "cycle-state").mkdir(parents=True)
        (ws / "scores").mkdir()
        (ws / "cycle-state" / "journey-recon.md").write_text(report)
        check = next(
            v for v in ValidationGenerator().generate(
                _agent(), {"fleet_score_count_truth_check": True}
            )
            if v["description"].startswith("Recon score-count")
        )
        return check["command"].replace("{workspace}", str(ws))

    def test_trailing_number_claim_is_caught(self, tmp_path: Path) -> None:
        # Disk has 0 agent scores; the report claims nine AFTER the noun.
        result = _run(self._command(tmp_path, "The agent scores total nine across the fleet.\n"))
        assert result.returncode == 1, result.stderr
        assert "-> 9" in result.stderr

    def test_leading_number_claim_still_caught(self, tmp_path: Path) -> None:
        result = _run(self._command(tmp_path, "We shipped 7 agent scores.\n"))
        assert result.returncode == 1

    def test_matching_claim_passes(self, tmp_path: Path) -> None:
        result = _run(self._command(tmp_path, "agent scores: zero so far.\n"))
        assert result.returncode == 0, result.stderr


class TestCadenzaCompletionBindsToThisRun:
    def _setup(self, tmp_path: Path) -> tuple[Path, Path, str]:
        agents_dir = tmp_path / "agents"
        cadenza = agents_dir / "journey" / "cadenzas" / "personal" / "active"
        cadenza.mkdir(parents=True)
        (cadenza / "02-status.md").write_text("journey recon cycle-state/journey-recon.md\n")
        (cadenza / "03-urgent-directives.md").write_text("none\n")
        (cadenza / "04-handoffs.md").write_text("none\n")
        workspace = tmp_path / "run"
        (workspace / "cycle-state").mkdir(parents=True)
        check = next(
            v for v in ValidationGenerator().generate(
                _agent(),
                {"cadenza_completion_validation": True,
                 "cadenzas": {"active": [{"directory": "{{workspace}}/shared/active",
                                          "as": "context", "phases": ["recon"]}]}},
                agents_dir=str(agents_dir),
            )
            if v["description"] == "Cadenza completion state for journey recon"
        )
        return cadenza, workspace, check["command"].replace("{workspace}", str(workspace))

    def test_stale_row_from_an_earlier_run_does_not_pass(self, tmp_path: Path) -> None:
        cadenza, workspace, command = self._setup(tmp_path)
        # A done row left by an earlier engagement, same relative path; this run
        # has NOT produced its artifact, so the row cannot be about this run.
        board = cadenza / "01-task-board.md"
        board.write_text(
            "| journey-T-001 | journey | done | old | cycle-state/journey-recon.md |\n"
        )
        result = _run(command)
        assert result.returncode == 1, result.stderr
        assert "missing done task-board row" in result.stderr

    def test_row_binding_this_runs_artifact_passes(self, tmp_path: Path) -> None:
        cadenza, workspace, command = self._setup(tmp_path)
        artifact = workspace / "cycle-state" / "journey-recon.md"
        artifact.write_text("observed\n")
        (cadenza / "01-task-board.md").write_text(
            f"| journey-T-002 | journey | done | recon | {artifact} |\n"
        )
        assert _run(command).returncode == 0

    def test_relative_path_row_passes_when_this_run_wrote_the_artifact(
        self, tmp_path: Path
    ) -> None:
        cadenza, workspace, command = self._setup(tmp_path)
        (workspace / "cycle-state" / "journey-recon.md").write_text("observed now\n")
        board = cadenza / "01-task-board.md"
        board.write_text(
            "| journey-T-003 | journey | done | recon | cycle-state/journey-recon.md |\n"
        )
        assert _run(command).returncode == 0
