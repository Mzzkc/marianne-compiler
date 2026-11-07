"""Lifecycle instructions and executable validators share a prefixed digest contract."""

from __future__ import annotations

import hashlib
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

from marianne_compiler.sheets import SheetComposer
from marianne_compiler.validations import ValidationGenerator


def _defaults(shape: str) -> dict:
    return {
        "score_shape": shape,
        "play_routing": {
            "memory_bloat_threshold": 3000,
            "stagnation_cycles": 3,
            "min_cycles_between_play": 5,
        },
    }


def _assert_hash_instruction(shape: str, stage: int, fields: tuple[str, ...]) -> None:
    result = SheetComposer().compose(
        {"name": "canyon", "voice": "Structure persists.", "focus": "architecture"},
        _defaults(shape),
    )
    instructions = " ".join(result["prompt_extensions"][stage])
    assert "sha256:" in instructions
    assert "64 lowercase hex" in instructions
    for field in fields:
        assert field in instructions


def test_targeted_work_debt_instruction_names_prefixed_hash_format() -> None:
    _assert_hash_instruction(
        "targeted-work", 8,
        ("recent_memory_before_sha256", "recent_memory_after_sha256"),
    )


def test_lifecycle_integration_instruction_names_prefixed_hash_format() -> None:
    _assert_hash_instruction(
        "lifecycle-integration", 12,
        (
            "source_debt_sha256", "memory_before_sha256", "memory_after_sha256",
            "source_evidence_sha256", "integration_receipt_sha256",
        ),
    )


@pytest.mark.parametrize(
    "bare_field",
    [None, "recent_memory_before_sha256", "recent_memory_after_sha256", "evidence"],
)
def test_validator_contract_round_trip(tmp_path: Path, bare_field: str | None) -> None:
    """Real snapshot/evidence bytes pass; stripping any required prefix fails."""
    agents = tmp_path / "agents"
    identity = agents / "canyon"
    metadata = identity / ".marianne"
    metadata.mkdir(parents=True)
    workspace = tmp_path / "workspace with spaces"
    workspace.mkdir()
    recent = identity / "recent.md"
    recent.write_text("Before this engagement.\n")
    checks = ValidationGenerator().generate(
        {"name": "canyon"}, _defaults("targeted-work"), agents_dir=str(agents),
    )

    def run_stage(stage: int) -> subprocess.CompletedProcess[str]:
        check = next(
            (item for item in checks
             if item.get("condition") == f"stage == {stage}"
             and item["type"] == "command_succeeds"
             and "SNAPSHOT=" in item["command"]),
            None,
        )
        if check is None:
            pytest.fail(
                f"stage-{stage} snapshot validator not found — did validations.py change?"
            )
        command = check["command"].replace("{workspace}", shlex.quote(str(workspace)))
        return subprocess.run(
            ["bash", "-c", command], capture_output=True,
            encoding="utf-8", errors="replace", timeout=10, check=False,
        )

    snapshot_result = run_stage(1)
    assert snapshot_result.returncode == 0, snapshot_result.stderr
    snapshot = workspace / "cycle-state/canyon-recent-before-targeted.md"
    recent.write_text("After: verified the debt binding against real evidence.\n")
    evidence = workspace / "observations.md"
    evidence.write_text("Observed an actual memory transition.\n")

    def digest(path: Path) -> str:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    debt = {
        "schema_version": 1,
        "kind": "marianne-lifecycle-debt",
        "agent": "canyon",
        "status": "pending",
        "source_engagement": "hash-contract-engagement",
        "pending_phases": ["consolidate", "reflect", "resurrect"],
        "recent_memory_before_snapshot": str(snapshot),
        "recent_memory_before_sha256": digest(snapshot),
        "recent_memory_after_sha256": digest(recent),
        "evidence": [{"path": evidence.name, "sha256": digest(evidence)}],
    }
    if bare_field == "evidence":
        debt["evidence"][0]["sha256"] = digest(evidence)[7:]
    elif bare_field is not None:
        debt[bare_field] = debt[bare_field][7:]
    (metadata / "pending-lifecycle-debt.yaml").write_text(yaml.safe_dump(debt))

    result = run_stage(8)
    if bare_field is None:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
        expected = "evidence hash mismatch" if bare_field == "evidence" else "lacks memory hashes"
        assert expected in result.stderr
