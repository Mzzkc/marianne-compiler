"""Tests for persistent-agent engagement score shapes."""

from __future__ import annotations

import hashlib
import shlex
import subprocess
from pathlib import Path

import yaml

from marianne_compiler.pipeline import CompilationPipeline
from marianne_compiler.sheets import SheetComposer
from marianne_compiler.validations import ValidationGenerator

AGENT = {"name": "canyon", "voice": "Structure persists.", "focus": "architecture"}


def test_targeted_work_records_explicit_lifecycle_debt() -> None:
    sheet = SheetComposer().compose(
        AGENT,
        {"score_shape": "targeted-work"},
        agents_dir=Path("/agents"),
    )

    assert set(sheet["skip_when"]) == {4, 6, 9, 10, 11, 12}
    assert all(item["command"] == "true" for item in sheet["skip_when"].values())
    extension = "\n".join(sheet["prompt_extensions"][8])
    assert "pending-lifecycle-debt.yaml" in extension
    assert "consolidate" in extension
    assert "reflection" in extension
    assert "resurrection" in extension


def test_lifecycle_integration_runs_only_debt_repayment_phases() -> None:
    sheet = SheetComposer().compose(
        AGENT,
        {"score_shape": "lifecycle-integration"},
        agents_dir=Path("/agents"),
    )

    assert set(sheet["skip_when"]) == {2, 3, 4, 5, 6, 7, 8}
    recon_extension = "\n".join(sheet["prompt_extensions"][1])
    resurrection_extension = "\n".join(sheet["prompt_extensions"][12])
    assert "pending-seed-conflicts.yaml" in recon_extension
    assert "pending-lifecycle-debt.yaml" in recon_extension
    assert "later recall" in resurrection_extension.lower()
    assert "close" in resurrection_extension.lower()


def test_targeted_work_mechanically_validates_debt_and_memory_hash() -> None:
    validations = ValidationGenerator().generate(
        AGENT,
        {"score_shape": "targeted-work"},
        agents_dir="/agents",
    )

    debt_path = "/agents/canyon/.marianne/pending-lifecycle-debt.yaml"
    assert any(
        item["type"] == "file_exists"
        and item.get("path") == debt_path
        and item.get("condition") == "stage == 8"
        for item in validations
    )
    debt_check = next(
        item
        for item in validations
        if item.get("description") == "Targeted lifecycle debt for canyon is grounded"
    )
    assert "recent_memory_after_sha256" in debt_check["command"]
    assert "recent_memory_before_snapshot" in debt_check["command"]
    assert 'status") != "pending"' in debt_check["command"]


def test_lifecycle_integration_mechanically_validates_recall_receipt() -> None:
    validations = ValidationGenerator().generate(
        AGENT,
        {"score_shape": "lifecycle-integration"},
        agents_dir="/agents",
    )

    receipt = "{workspace}/cycle-state/canyon-lifecycle-integration-receipt.yaml"
    assert any(
        item["type"] == "file_exists"
        and item.get("path") == receipt
        and item.get("condition") == "stage == 12"
        for item in validations
    )
    receipt_check = next(
        item
        for item in validations
        if item.get("description") == "Lifecycle integration recall for canyon is grounded"
    )
    assert "later_recall" in receipt_check["command"]
    assert "source_memory" in receipt_check["command"]


def test_targeted_debt_validation_reaches_canonical_memory_bytes(
    tmp_path: Path,
) -> None:
    agent_dir = tmp_path / "agents" / "canyon"
    agent_dir.mkdir(parents=True)
    recent = agent_dir / "recent.md"
    recent.write_text("before targeted work\n")
    workspace = tmp_path / "workspace"
    validations = ValidationGenerator().generate(
        AGENT,
        {"score_shape": "targeted-work"},
        agents_dir=str(tmp_path / "agents"),
    )
    snapshot_command = next(
        item["command"]
        for item in validations
        if item.get("description") == "Capture targeted memory baseline for canyon"
    ).replace("{workspace}", shlex.quote(str(workspace)))
    assert subprocess.run(["bash", "-c", snapshot_command], check=False).returncode == 0
    snapshot = workspace / "cycle-state" / "canyon-recent-before-targeted.md"
    before = "sha256:" + hashlib.sha256(snapshot.read_bytes()).hexdigest()
    recent.write_text("before targeted work\ngrounded learning\n")
    after = "sha256:" + hashlib.sha256(recent.read_bytes()).hexdigest()
    evidence = workspace / "cycle-state" / "canyon-aar.md"
    evidence.write_text("grounded evidence\n")
    evidence_hash = "sha256:" + hashlib.sha256(evidence.read_bytes()).hexdigest()
    debt = agent_dir / ".marianne" / "pending-lifecycle-debt.yaml"
    debt.parent.mkdir()
    debt.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "kind": "marianne-lifecycle-debt",
                "agent": "canyon",
                "status": "pending",
                "source_engagement": "targeted-1",
                "evidence": [
                    {"path": "cycle-state/canyon-aar.md", "sha256": evidence_hash}
                ],
                "pending_phases": ["consolidate", "reflect", "resurrect"],
                "recent_memory_before_snapshot": str(snapshot),
                "recent_memory_before_sha256": before,
                "recent_memory_after_sha256": after,
            }
        )
    )
    command = next(
        item["command"]
        for item in validations
        if item.get("description") == "Targeted lifecycle debt for canyon is grounded"
    ).replace("{workspace}", shlex.quote(str(workspace)))

    assert subprocess.run(["bash", "-c", command], check=False).returncode == 0
    debt_doc = yaml.safe_load(debt.read_text())
    debt_doc["recent_memory_before_sha256"] = "sha256:" + "0" * 64
    debt.write_text(yaml.safe_dump(debt_doc))
    assert subprocess.run(["bash", "-c", command], check=False).returncode != 0


def test_lifecycle_recall_validation_rejects_counterfeit_receipt(
    tmp_path: Path,
) -> None:
    agent_dir = tmp_path / "agents" / "canyon"
    agent_dir.mkdir(parents=True)
    recent = agent_dir / "recent.md"
    recent.write_text("targeted learning\n")
    workspace = tmp_path / "workspace"
    evidence = workspace / "cycle-state" / "targeted-aar.md"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("queue lesson evidence\n")
    evidence_hash = "sha256:" + hashlib.sha256(evidence.read_bytes()).hexdigest()
    debt_path = agent_dir / ".marianne" / "pending-lifecycle-debt.yaml"
    debt_path.parent.mkdir()
    debt_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "kind": "marianne-lifecycle-debt",
                "agent": "canyon",
                "status": "pending",
                "source_engagement": "targeted-1",
                "evidence": [{"path": str(evidence), "sha256": evidence_hash}],
                "pending_phases": ["consolidate", "reflect", "resurrect"],
                "recent_memory_before_snapshot": "prior.md",
                "recent_memory_before_sha256": "sha256:" + "1" * 64,
                "recent_memory_after_sha256": (
                    "sha256:" + hashlib.sha256(recent.read_bytes()).hexdigest()
                ),
            }
        )
    )
    validations = ValidationGenerator().generate(
        AGENT,
        {"score_shape": "lifecycle-integration"},
        agents_dir=str(tmp_path / "agents"),
    )
    snapshot_command = next(
        item["command"]
        for item in validations
        if item.get("description") == "Capture lifecycle inputs for canyon"
    ).replace("{workspace}", shlex.quote(str(workspace)))
    assert subprocess.run(["bash", "-c", snapshot_command], check=False).returncode == 0
    source_debt = workspace / "cycle-state" / "canyon-source-lifecycle-debt.yaml"
    source_debt_hash = "sha256:" + hashlib.sha256(source_debt.read_bytes()).hexdigest()
    before = yaml.safe_load(source_debt.read_text())["recent_memory_after_sha256"]
    recent.write_text("targeted learning\nintegrated queue lesson\n")
    after = "sha256:" + hashlib.sha256(recent.read_bytes()).hexdigest()
    receipt = workspace / "cycle-state" / "canyon-lifecycle-integration-receipt.yaml"
    document = {
        "schema_version": 1,
        "kind": "marianne-lifecycle-integration",
        "agent": "canyon",
        "status": "integrated",
        "source_debt_sha256": source_debt_hash,
        "source_memory": "recent.md",
        "later_recall": {
            "source_engagement": "targeted-1",
            "source_evidence_sha256": evidence_hash,
            "recalled_learning": "Queued lanes carry operating cost.",
            "present_application": "Kept the free lane supplementary.",
        },
        "closed_debt": ["targeted-1"],
        "memory_before_sha256": before,
        "memory_after_sha256": after,
        "seed_resolution_receipt": None,
    }
    receipt.write_text(yaml.safe_dump(document))
    receipt_hash = "sha256:" + hashlib.sha256(receipt.read_bytes()).hexdigest()
    closed_debt = yaml.safe_load(source_debt.read_text())
    closed_debt["status"] = "integrated"
    closed_debt["source_debt_sha256"] = source_debt_hash
    closed_debt["integration_receipt_sha256"] = receipt_hash
    debt_path.write_text(yaml.safe_dump(closed_debt))
    command = next(
        item["command"]
        for item in validations
        if item.get("description") == "Lifecycle integration recall for canyon is grounded"
    ).replace("{workspace}", shlex.quote(str(workspace)))

    assert subprocess.run(["bash", "-c", command], check=False).returncode == 0
    document["memory_before_sha256"] = "sha256:" + "0" * 64
    receipt.write_text(yaml.safe_dump(document))
    assert subprocess.run(["bash", "-c", command], check=False).returncode != 0


def test_full_lifecycle_has_no_shape_forced_skips() -> None:
    sheet = SheetComposer().compose(
        AGENT,
        {"score_shape": "full-lifecycle"},
        agents_dir=Path("/agents"),
    )
    assert "skip_when" not in sheet
    assert "prompt_extensions" not in sheet


def test_self_chain_can_be_disabled_for_one_engagement(tmp_path: Path) -> None:
    config = {
        "project": {"name": "one-run", "workspace": str(tmp_path / "workspace")},
        "defaults": {"self_chain": False},
        "agents": [AGENT],
    }
    output = tmp_path / "scores"
    pipeline = CompilationPipeline(agents_dir=tmp_path / "agents")

    pipeline.compile_config(config, output)

    score = yaml.safe_load((output / "canyon.yaml").read_text())
    assert "on_success" not in score
