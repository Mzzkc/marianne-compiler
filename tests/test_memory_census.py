"""Behavioral tests for read-only persistent-agent memory discovery."""

from __future__ import annotations

from pathlib import Path

import yaml

from marianne_compiler.memory_census import census_agent_memory


def _write_agent(root: Path, name: str, marker: str) -> Path:
    agent = root / name
    agent.mkdir(parents=True)
    (agent / "identity.md").write_text(f"# {name}\n\n{marker}\n")
    (agent / "profile.yaml").write_text(
        yaml.safe_dump({"name": name, "cycle_count": 1}, sort_keys=False)
    )
    (agent / "recent.md").write_text(f"# Recent\n\n{marker}\n")
    (agent / "growth.md").write_text(f"# Growth\n\n{marker}\n")
    return agent


def test_census_deduplicates_alias_and_classifies_snapshots(tmp_path: Path) -> None:
    canonical = tmp_path / "AGENTS" / "agents"
    canyon = _write_agent(canonical, "canyon", "canonical")
    alias = tmp_path / ".marianne" / "agents"
    alias.parent.mkdir(parents=True)
    alias.symlink_to(canonical, target_is_directory=True)
    snapshot_root = tmp_path / "WORSKPACES" / "campaign" / "agents"
    _write_agent(snapshot_root, "canyon", "snapshot divergence")
    _write_agent(snapshot_root, "forge", "snapshot without authority")

    report = census_agent_memory(
        canonical_root=canonical,
        search_roots=[alias, tmp_path / "WORSKPACES"],
    )

    assert report["canonical_root"] == str(canonical.resolve())
    assert [entry["path"] for entry in report["canonical"]] == [str(canyon.resolve())]
    assert len(report["aliases"]) == 1
    assert report["aliases"][0]["path"] == str(alias.resolve())
    divergent = {entry["agent_id"]: entry for entry in report["snapshots"]}
    assert divergent["canyon"]["relationship"] == "divergent_from_canonical"
    assert divergent["forge"]["relationship"] == "no_canonical_agent"


def test_census_is_read_only(tmp_path: Path) -> None:
    canonical = tmp_path / "agents"
    _write_agent(canonical, "canyon", "unchanged")
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    report = census_agent_memory(canonical_root=canonical, search_roots=[tmp_path])

    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert report["unknown"] == []
    assert before == after


def test_census_reports_partial_unknown_identity_tree(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical"
    _write_agent(canonical, "canyon", "canonical")
    partial = tmp_path / "other" / "runtime"
    partial.mkdir(parents=True)
    (partial / "profile.yaml").write_text("name: runtime\ncycle_count: 0\n")

    report = census_agent_memory(canonical_root=canonical, search_roots=[tmp_path / "other"])

    assert len(report["unknown"]) == 1
    assert report["unknown"][0]["agent_id"] == "runtime"
    assert report["unknown"][0]["missing_layers"] == [
        "growth.md",
        "identity.md",
        "recent.md",
    ]
