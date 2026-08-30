"""Tests for conservative installation of portable persistent-agent packages."""

from __future__ import annotations

import hashlib
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

from marianne_compiler.agent_package import (
    generate_agent_package,
    install_agent_package,
)


def _config(seed_version: str = "1.0.0") -> dict[str, object]:
    return {
        "project": {"name": "portable-cast"},
        "defaults": {
            "techniques": {
                "identity": {"kind": "skill", "phases": ["all"]},
            },
            "instruments": {
                "work": {"primary": {"instrument": "claude-code"}},
            },
        },
        "agents": [
            {
                "name": "canyon",
                "seed_version": seed_version,
                "voice": "Structure persists.",
                "focus": "architecture",
            }
        ],
    }


def _refresh_package_asset_hashes(package: Path, agent_name: str) -> None:
    """Model a newly generated release after a fixture changes package assets."""
    roster_path = package / "roster.yaml"
    roster = yaml.safe_load(roster_path.read_text())
    roster_agent = next(item for item in roster["agents"] if item["id"] == agent_name)
    roots = [
        package / "seeds" / agent_name,
        package / "scores" / agent_name,
    ]
    roster_agent["asset_hashes"] = {
        path.relative_to(package).as_posix(): (
            "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        )
        for root in roots
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
    roster_path.write_text(yaml.safe_dump(roster, sort_keys=False))


def test_install_bootstraps_agent_scores_cadenza_and_techniques(tmp_path: Path) -> None:
    technique_source = tmp_path / "source-techniques"
    technique_source.mkdir()
    (technique_source / "identity.md").write_text("# Identity\n")
    package = tmp_path / "package"
    generate_agent_package(_config(), package, techniques_dir=technique_source)
    agents_dir = tmp_path / "agents"
    techniques_dir = tmp_path / "techniques"

    report = install_agent_package(
        package,
        techniques_source=technique_source,
        agents_dir=agents_dir,
        techniques_dir=techniques_dir,
    )

    assert report["conflicts"] == []
    assert (agents_dir / "canyon" / "identity.md").is_file()
    assert (agents_dir / "canyon" / "scores" / "full-lifecycle.yaml").is_file()
    assert (agents_dir / "canyon" / "workspaces").is_dir()
    installed_score = yaml.safe_load(
        (agents_dir / "canyon" / "scores" / "full-lifecycle.yaml").read_text()
    )
    assert installed_score["workspace"] == str(
        agents_dir
        / "canyon"
        / "workspaces"
        / "REQUIRES-LIVE-BINDING-full-lifecycle"
    )
    assert installed_score["sheet"]["prelude"][0]["file"] == str(
        agents_dir / "canyon" / "identity.md"
    )
    assert installed_score["techniques"]["identity"]["config"]["path"] == str(
        techniques_dir / "identity.md"
    )
    active = agents_dir / "canyon" / "cadenzas" / "personal" / "active"
    assert sorted(path.name for path in active.iterdir()) == [
        "01-task-board.md",
        "02-status.md",
        "03-urgent-directives.md",
        "04-handoffs.md",
    ]
    assert (techniques_dir / "identity.md").read_text() == "# Identity\n"


def test_install_preserves_locally_changed_managed_assets(tmp_path: Path) -> None:
    technique_source = tmp_path / "source-techniques"
    technique_source.mkdir()
    source_technique = technique_source / "identity.md"
    source_technique.write_text("# Identity v1\n")
    package = tmp_path / "package"
    generate_agent_package(_config(), package, techniques_dir=technique_source)
    agents_dir = tmp_path / "agents"
    techniques_dir = tmp_path / "techniques"
    install_agent_package(
        package,
        techniques_source=technique_source,
        agents_dir=agents_dir,
        techniques_dir=techniques_dir,
    )
    installed = techniques_dir / "identity.md"
    installed.write_text("# Locally learned method\n")
    source_technique.write_text("# Identity v2\n")

    report = install_agent_package(
        package,
        techniques_source=technique_source,
        agents_dir=agents_dir,
        techniques_dir=techniques_dir,
    )

    assert installed.read_text() == "# Locally learned method\n"
    assert any(item["path"] == "identity.md" for item in report["conflicts"])
    pending = yaml.safe_load(
        (techniques_dir / ".marianne-agent-package-conflicts.yaml").read_text()
    )
    assert pending["conflicts"][0]["reason"] == "locally_modified_managed_asset"


def test_install_retires_removed_managed_assets_but_preserves_local_edits(
    tmp_path: Path,
) -> None:
    technique_source = tmp_path / "source-techniques"
    technique_source.mkdir()
    (technique_source / "identity.md").write_text("# Identity\n")
    package = tmp_path / "package"
    generate_agent_package(_config(), package, techniques_dir=technique_source)
    old_source = (
        package
        / "seeds"
        / "canyon"
        / "cadenzas"
        / "personal"
        / "active"
        / "00-old-directive.md"
    )
    old_source.write_text("# Old directive\n")
    edited_source = old_source.with_name("00-edited-directive.md")
    edited_source.write_text("# Old editable directive\n")
    _refresh_package_asset_hashes(package, "canyon")
    agents_dir = tmp_path / "agents"
    techniques_dir = tmp_path / "techniques"
    install_agent_package(
        package,
        techniques_source=technique_source,
        agents_dir=agents_dir,
        techniques_dir=techniques_dir,
    )
    old_target = agents_dir / "canyon" / "cadenzas" / "personal" / "active" / old_source.name
    edited_target = old_target.with_name(edited_source.name)
    edited_target.write_text("# Agent's lived local edit\n")
    old_source.unlink()
    edited_source.unlink()
    _refresh_package_asset_hashes(package, "canyon")

    report = install_agent_package(
        package,
        techniques_source=technique_source,
        agents_dir=agents_dir,
        techniques_dir=techniques_dir,
    )

    assert not old_target.exists()
    assert edited_target.read_text() == "# Agent's lived local edit\n"
    assert any(
        item["path"].endswith("00-old-directive.md")
        and item["action"] == "removed"
        for item in report["actions"]
    )
    assert any(
        item["path"].endswith("00-edited-directive.md")
        and item["reason"] == "package_removed_locally_modified_asset"
        for item in report["conflicts"]
    )


def test_install_dry_run_does_not_create_targets(tmp_path: Path) -> None:
    technique_source = tmp_path / "source-techniques"
    technique_source.mkdir()
    (technique_source / "identity.md").write_text("# Identity\n")
    package = tmp_path / "package"
    generate_agent_package(_config(), package, techniques_dir=technique_source)
    agents_dir = tmp_path / "agents"
    techniques_dir = tmp_path / "techniques"

    report = install_agent_package(
        package,
        techniques_source=technique_source,
        agents_dir=agents_dir,
        techniques_dir=techniques_dir,
        dry_run=True,
    )

    assert report["status"] == "dry_run"
    assert not agents_dir.exists()
    assert not techniques_dir.exists()


def test_install_validates_every_score_before_seeding_identity(tmp_path: Path) -> None:
    technique_source = tmp_path / "source-techniques"
    technique_source.mkdir()
    (technique_source / "identity.md").write_text("# Identity\n")
    package = tmp_path / "package"
    generate_agent_package(_config(), package, techniques_dir=technique_source)
    (package / "scores" / "canyon" / "lifecycle-integration.yaml").write_text(
        "not: [valid"
    )
    agents_dir = tmp_path / "agents"

    with pytest.raises(ValueError, match="Invalid packaged score"):
        install_agent_package(
            package,
            techniques_source=technique_source,
            agents_dir=agents_dir,
            techniques_dir=tmp_path / "techniques",
        )

    assert not agents_dir.exists()


@pytest.mark.parametrize(
    "agent_id",
    ["../outside", "/tmp/outside", "musician-ember", ".hidden", "Canyon"],
)
def test_install_rejects_uncontained_or_reserved_agent_ids_before_writing(
    tmp_path: Path,
    agent_id: str,
) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "roster.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "agents": [{"id": agent_id}]})
    )
    techniques_source = tmp_path / "source-techniques"
    techniques_source.mkdir()
    agents_dir = tmp_path / "agents"

    with pytest.raises(ValueError, match="agent id"):
        install_agent_package(
            package,
            techniques_source=techniques_source,
            agents_dir=agents_dir,
            techniques_dir=tmp_path / "techniques",
        )

    assert not agents_dir.exists()


def test_install_rejects_roster_seed_identity_mismatch_before_writing(
    tmp_path: Path,
) -> None:
    technique_source = tmp_path / "source-techniques"
    technique_source.mkdir()
    package = tmp_path / "package"
    generate_agent_package(_config(), package, techniques_dir=technique_source)
    seed_path = package / "seeds" / "canyon" / "seed.yaml"
    seed = yaml.safe_load(seed_path.read_text())
    seed["name"] = "forge"
    seed_path.write_text(yaml.safe_dump(seed))
    agents_dir = tmp_path / "agents"

    with pytest.raises(ValueError, match="does not match roster id"):
        install_agent_package(
            package,
            techniques_source=technique_source,
            agents_dir=agents_dir,
            techniques_dir=tmp_path / "techniques",
        )

    assert not agents_dir.exists()


def test_install_rejects_roster_seed_version_or_asset_hash_mismatch_before_writing(
    tmp_path: Path,
) -> None:
    technique_source = tmp_path / "source-techniques"
    technique_source.mkdir()
    package = tmp_path / "package"
    generate_agent_package(_config(), package, techniques_dir=technique_source)
    seed_path = package / "seeds" / "canyon" / "seed.yaml"
    seed = yaml.safe_load(seed_path.read_text())
    seed["seed_version"] = "2.0.0"
    seed_path.write_text(yaml.safe_dump(seed))
    agents_dir = tmp_path / "agents"

    with pytest.raises(ValueError, match="seed version|asset hash"):
        install_agent_package(
            package,
            techniques_source=technique_source,
            agents_dir=agents_dir,
            techniques_dir=tmp_path / "techniques",
        )

    assert not agents_dir.exists()


def test_install_rejects_symlinked_managed_parent_without_writing_outside(
    tmp_path: Path,
) -> None:
    technique_source = tmp_path / "source-techniques"
    technique_source.mkdir()
    package = tmp_path / "package"
    generate_agent_package(_config(), package, techniques_dir=technique_source)
    agents_dir = tmp_path / "agents"
    techniques_dir = tmp_path / "techniques"
    install_agent_package(
        package,
        techniques_source=technique_source,
        agents_dir=agents_dir,
        techniques_dir=techniques_dir,
    )
    score_root = agents_dir / "canyon" / "scores"
    for path in score_root.iterdir():
        path.unlink()
    score_root.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    score_root.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="escapes managed root|symlink"):
        install_agent_package(
            package,
            techniques_source=technique_source,
            agents_dir=agents_dir,
            techniques_dir=techniques_dir,
        )

    assert list(outside.iterdir()) == []


def test_install_rejects_symlinked_agent_root_without_writing_outside(
    tmp_path: Path,
) -> None:
    technique_source = tmp_path / "source-techniques"
    technique_source.mkdir()
    package = tmp_path / "package"
    generate_agent_package(_config(), package, techniques_dir=technique_source)
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    outside = tmp_path / "outside-agent"
    outside.mkdir()
    (agents_dir / "canyon").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="agent root.*symlink"):
        install_agent_package(
            package,
            techniques_source=technique_source,
            agents_dir=agents_dir,
            techniques_dir=tmp_path / "techniques",
        )

    assert list(outside.iterdir()) == []


def test_installed_score_shell_commands_support_custom_roots_with_spaces(
    tmp_path: Path,
) -> None:
    technique_source = tmp_path / "source techniques"
    technique_source.mkdir()
    (technique_source / "identity.md").write_text("# Identity\n")
    package = tmp_path / "package"
    generate_agent_package(_config(), package, techniques_dir=technique_source)
    agents_dir = tmp_path / "Agent Root"
    techniques_dir = tmp_path / "Technique Root"
    install_agent_package(
        package,
        techniques_source=technique_source,
        agents_dir=agents_dir,
        techniques_dir=techniques_dir,
    )
    agent_dir = agents_dir / "canyon"
    recent = agent_dir / "recent.md"
    score = yaml.safe_load(
        (agent_dir / "scores" / "targeted-work.yaml").read_text()
    )
    workspace = Path(score["workspace"])
    capture = next(
        item["command"]
        for item in score["validations"]
        if item.get("description") == "Capture targeted memory baseline for canyon"
    ).replace("{workspace}", shlex.quote(str(workspace)))
    captured = subprocess.run(
        ["bash", "-c", capture], check=False, capture_output=True, text=True
    )
    assert captured.returncode == 0, captured.stderr
    snapshot = workspace / "cycle-state" / "canyon-recent-before-targeted.md"
    before_hash = "sha256:" + hashlib.sha256(snapshot.read_bytes()).hexdigest()
    recent.write_text(recent.read_text() + "\nGrounded custom-root learning.\n")
    recent_hash = "sha256:" + hashlib.sha256(recent.read_bytes()).hexdigest()
    evidence = workspace / "cycle-state" / "canyon-aar.md"
    evidence.write_text("custom-root evidence\n")
    evidence_hash = "sha256:" + hashlib.sha256(evidence.read_bytes()).hexdigest()
    debt = agent_dir / ".marianne" / "pending-lifecycle-debt.yaml"
    debt.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "kind": "marianne-lifecycle-debt",
                "agent": "canyon",
                "status": "pending",
                "pending_phases": ["consolidate", "reflect", "resurrect"],
                "source_engagement": "test",
                "evidence": [{"path": str(evidence), "sha256": evidence_hash}],
                "recent_memory_before_snapshot": str(snapshot),
                "recent_memory_before_sha256": before_hash,
                "recent_memory_after_sha256": recent_hash,
            }
        )
    )
    command = next(
        item["command"]
        for item in score["validations"]
        if item.get("description") == "Targeted lifecycle debt for canyon is grounded"
    )

    completed = subprocess.run(
        ["bash", "-c", command.replace("{workspace}", shlex.quote(str(workspace)))],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
