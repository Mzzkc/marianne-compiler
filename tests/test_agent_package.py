"""Tests for deterministic portable persistent-agent packages."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from marianne_compiler.agent_package import generate_agent_package


def _config() -> dict[str, object]:
    return {
        "project": {"name": "portable-cast"},
        "defaults": {
            "techniques": {
                "identity": {"kind": "skill", "phases": ["reflect", "resurrect"]},
            },
            "instruments": {
                "work": {
                    "primary": {"instrument": "claude-code"},
                    "fallbacks": [{"instrument": "codex-cli"}],
                }
            },
        },
        "agents": [
            {
                "name": "canyon",
                "seed_version": "1.0.0",
                "voice": "Structure persists.",
                "focus": "architecture",
                "role": "architect",
                "techniques": {
                    "canyon-specialist": {
                        "kind": "skill",
                        "phases": ["plan", "work", "inspect", "aar"],
                    }
                },
            }
        ],
    }


def test_package_contains_seed_roster_and_three_concrete_scores(tmp_path: Path) -> None:
    techniques = tmp_path / "techniques"
    techniques.mkdir()
    (techniques / "identity.md").write_text("# Identity Technique\n")
    (techniques / "canyon-specialist.md").write_text("# Canyon Specialist\n")
    output = tmp_path / "agent-scores"

    generated = generate_agent_package(_config(), output, techniques_dir=techniques)

    assert len(generated) == 9
    roster = yaml.safe_load((output / "roster.yaml").read_text())
    assert roster["agents"][0]["id"] == "canyon"
    assert roster["agents"][0]["scores"] == {
        "full_lifecycle": "scores/canyon/full-lifecycle.yaml",
        "targeted_work": "scores/canyon/targeted-work.yaml",
        "lifecycle_integration": "scores/canyon/lifecycle-integration.yaml",
    }
    seed = yaml.safe_load((output / "seeds" / "canyon" / "seed.yaml").read_text())
    assert seed["name"] == "canyon"
    assert seed["seed_version"] == "1.0.0"

    for shape in ("full-lifecycle", "targeted-work", "lifecycle-integration"):
        score_path = output / "scores" / "canyon" / f"{shape}.yaml"
        score_text = score_path.read_text()
        score = yaml.safe_load(score_text)
        assert score["name"] == f"{shape}-canyon"
        assert score["workspace"] == (
            "~/.marianne/agents/canyon/workspaces/"
            f"REQUIRES-LIVE-BINDING-{shape}"
        )
        assert score["sheet"]["prelude"][0]["file"] == (
            "~/.marianne/agents/canyon/identity.md"
        )
        assert score["sheet"]["prelude"][0]["required"] is True
        shared = [
            item
            for items in score["sheet"]["cadenzas"].values()
            for item in items
            if "directory" in item
        ]
        assert any(
            item["directory"]
            == "~/.marianne/agents/canyon/cadenzas/personal/active"
            for item in shared
        )
        assert score["techniques"]["canyon-specialist"]["config"]["path"] == (
            "~/.marianne/techniques/canyon-specialist.md"
        )
        assert score["techniques"]["canyon-specialist"]["required"] is True
        contract = score["prompt"]["variables"]["marianne_agent"]
        assert contract["agent_id"] == "canyon"
        assert contract["score_shape"] == shape
        assert contract["phase_requirements"] == {}
        assert contract["routing_receipts"] == {}
        assert "on_success" not in score
        assert str(tmp_path) not in score_text

    active_seed = output / "seeds" / "canyon" / "cadenzas" / "personal" / "active"
    assert sorted(path.name for path in active_seed.iterdir()) == [
        "01-task-board.md",
        "02-status.md",
        "03-urgent-directives.md",
        "04-handoffs.md",
    ]


def test_package_generation_is_byte_deterministic(tmp_path: Path) -> None:
    techniques = tmp_path / "techniques"
    techniques.mkdir()
    (techniques / "identity.md").write_text("# Identity Technique\n")
    (techniques / "canyon-specialist.md").write_text("# Canyon Specialist\n")
    output = tmp_path / "agent-scores"

    generate_agent_package(_config(), output, techniques_dir=techniques)
    before = {
        path.relative_to(output): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }
    generate_agent_package(_config(), output, techniques_dir=techniques)
    after = {
        path.relative_to(output): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }

    assert before == after


def test_package_generation_rejects_path_like_agent_name_before_writing(
    tmp_path: Path,
) -> None:
    config = _config()
    config["agents"][0]["name"] = "../outside"  # type: ignore[index]
    output = tmp_path / "agent-scores"
    techniques = tmp_path / "techniques"
    techniques.mkdir()

    with pytest.raises(ValueError, match="agent id"):
        generate_agent_package(config, output, techniques_dir=techniques)

    assert not output.exists()


def test_package_generation_failure_leaves_published_package_unchanged(
    tmp_path: Path,
) -> None:
    techniques = tmp_path / "techniques"
    techniques.mkdir()
    (techniques / "identity.md").write_text("# Identity Technique\n")
    (techniques / "canyon-specialist.md").write_text("# Canyon Specialist\n")
    output = tmp_path / "agent-scores"
    generate_agent_package(_config(), output, techniques_dir=techniques)
    (output / "README.md").write_text("human-maintained\n")
    before = {
        path.relative_to(output): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }
    updated = _config()
    updated["agents"][0]["seed_version"] = "2.0.0"  # type: ignore[index]

    from marianne_compiler import agent_package

    original = agent_package._write_yaml
    calls = 0

    def interrupted(path: Path, value: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("simulated package generation interruption")
        original(path, value)

    with (
        patch.object(agent_package, "_write_yaml", side_effect=interrupted),
        pytest.raises(OSError, match="simulated package generation"),
    ):
        generate_agent_package(updated, output, techniques_dir=techniques)

    after = {
        path.relative_to(output): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }
    assert after == before
