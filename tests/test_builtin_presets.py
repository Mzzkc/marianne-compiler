"""Tests for built-in compiler presets."""

from __future__ import annotations

from pathlib import Path

import yaml

from marianne_compiler.pipeline import CompilationPipeline
from marianne_compiler.presets import load_builtin_preset, prepare_builtin_preset


def test_generic_fleet_preset_loads() -> None:
    config = load_builtin_preset("generic-fleet")

    assert config["project"]["name"] == "generic-agent-fleet"
    assert len(config["agents"]) == 32
    assert "flowspec" not in str(config).lower()
    assert "llama-4-maverick" not in str(config).lower()
    assert "kimi" not in str(config).lower()
    assert "gemini-cli" not in str(config)

    default_instruments = config["defaults"]["instruments"]
    codex_fallback_tiers = {
        tier
        for tier, tier_config in default_instruments.items()
        for fallback in tier_config.get("fallbacks", [])
        if fallback.get("instrument") == "codex-cli"
    }
    assert codex_fallback_tiers == {"work", "integration", "play", "inspect"}
    assert all(
        tier_config["primary"].get("instrument") != "codex-cli"
        for tier_config in default_instruments.values()
    )
    gemini_flash_primary_tiers = {
        tier
        for tier, tier_config in default_instruments.items()
        if tier_config["primary"].get("instrument") == "antigravity"
        and tier_config["primary"].get("model") == "gemini-3.5-flash"
    }
    assert gemini_flash_primary_tiers == {
        "recon",
        "plan",
        "inspect",
        "aar",
        "consolidate",
    }


def test_generic_fleet_preset_compiles(tmp_path: Path) -> None:
    config = prepare_builtin_preset(
        load_builtin_preset("generic-fleet"),
        name="generic-fleet",
        cwd=Path.cwd(),
        workspace=tmp_path / "workspace",
    )
    pipeline = CompilationPipeline(agents_dir=tmp_path / "agents")

    score_paths = pipeline.compile_config(config, tmp_path / "scores", base_dir=Path.cwd())

    agent_scores = [path for path in score_paths if path.name != "fleet.yaml"]
    assert len(agent_scores) == 32
    assert (tmp_path / "scores" / "fleet.yaml").exists()
    assert not list((tmp_path / "scores").glob("*.agent-card.yaml"))

    canyon = yaml.safe_load((tmp_path / "scores" / "canyon.yaml").read_text())
    assert "skip_when" in canyon["sheet"]
    assert "skip_when_command" not in canyon["sheet"]
    assert canyon["sheet"]["per_sheet_instruments"][4] == "cli"
    assert canyon["sheet"]["per_sheet_instruments"][5] == "claude-code--glm-5-turbo"
    assert canyon["sheet"]["per_sheet_instruments"][11] == "cli"
    assert canyon["techniques"]["a2a"]["kind"] == "protocol"
    assert "3" in canyon["techniques"]["a2a"]["phases"]
    assert canyon["techniques"]["filesystem"]["kind"] == "mcp"
    assert "3" in canyon["techniques"]["filesystem"]["phases"]
    assert "4" not in canyon["techniques"]["filesystem"]["phases"]
    assert "11" not in canyon["techniques"]["filesystem"]["phases"]
    assert "symbols-python" not in canyon["techniques"]
    assert canyon["agent_card"]["name"] == "canyon"
    assert "claude-code--glm-5.2-1m" in canyon["instruments"]
    assert "antigravity--gemini-3.5-flash" in canyon["instruments"]
    assert "gemini-cli--gemini-3.5-flash" not in canyon["instruments"]
    identity_dir = canyon["prompt"]["variables"]["agent_identity_dir"]
    assert str(tmp_path / "agents" / "canyon") in identity_dir
    for filename in ("identity.md", "profile.yaml", "recent.md", "growth.md"):
        assert (tmp_path / "agents" / "canyon" / filename).exists()
    assert (tmp_path / "agents" / "canyon" / "archive").is_dir()

    active_dir = tmp_path / "workspace" / "shared" / "active"
    assert active_dir.is_dir()
    assert (active_dir / "00-cadenza-coordination.md").exists()
    assert (active_dir / "01-task-board.md").exists()
    assert (active_dir / "02-agent-status.md").exists()
    assert (active_dir / "03-findings.md").exists()
    assert (active_dir / "04-decision-log.md").exists()
    assert (active_dir / "05-directives.md").exists()
    assert (active_dir / "06-handoff-index.md").exists()
    assert "Concurrent Write Safety" in (
        active_dir / "00-cadenza-coordination.md"
    ).read_text()
    assert "owner-scoped row once" in (
        active_dir / "01-task-board.md"
    ).read_text()

    cadenza_dirs = [
        item["directory"]
        for items in canyon["sheet"]["cadenzas"].values()
        for item in items
        if "directory" in item
    ]
    assert "{{workspace}}/shared/active" in cadenza_dirs


def test_generic_fleet_agents_have_specialist_techniques() -> None:
    config = load_builtin_preset("generic-fleet")
    agents = config["agents"]

    for agent in agents:
        name = agent["name"]
        techniques = agent.get("techniques", {})
        specialist = f"{name}-specialist"
        assert specialist in techniques
        assert techniques[specialist]["kind"] == "skill"
        assert "work" in techniques[specialist]["phases"]

        packaged = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "marianne_compiler"
            / "assets"
            / "techniques"
            / f"{specialist}.md"
        )
        assert packaged.exists()
        text = packaged.read_text()
        assert f"# {name.title()} Specialist Technique" in text
        assert "shared/active/01-task-board.md" in text


def test_generic_fleet_workspace_seed_preserves_existing_files(tmp_path: Path) -> None:
    config = prepare_builtin_preset(
        load_builtin_preset("generic-fleet"),
        name="generic-fleet",
        cwd=Path.cwd(),
        workspace=tmp_path / "workspace",
    )
    pipeline = CompilationPipeline(agents_dir=tmp_path / "agents")

    pipeline.compile_config(config, tmp_path / "scores", base_dir=Path.cwd())
    task_board = tmp_path / "workspace" / "shared" / "active" / "01-task-board.md"
    custom = "# Task Board\n\ncustom live coordination state\n"
    task_board.write_text(custom)

    pipeline.compile_config(config, tmp_path / "scores", base_dir=Path.cwd())

    assert task_board.read_text() == custom


def test_generic_fleet_preset_uses_packaged_techniques_outside_repo(
    tmp_path: Path,
) -> None:
    outside_repo = tmp_path / "outside-project"
    outside_repo.mkdir()
    config = prepare_builtin_preset(
        load_builtin_preset("generic-fleet"),
        name="generic-fleet",
        cwd=outside_repo,
        workspace=tmp_path / "workspace",
    )

    techniques_dir = Path(config["techniques_dir"])
    assert techniques_dir.name == "techniques"
    assert (techniques_dir / "mateship.md").exists()
    assert (techniques_dir / "canyon-specialist.md").exists()

    pipeline = CompilationPipeline(agents_dir=tmp_path / "agents")
    pipeline.compile_config(config, tmp_path / "scores", base_dir=outside_repo)
    canyon = yaml.safe_load((tmp_path / "scores" / "canyon.yaml").read_text())

    files = [
        item["file"]
        for items in canyon["sheet"]["cadenzas"].values()
        for item in items
        if "file" in item
    ]
    assert str(techniques_dir / "mateship.md") not in files
    assert str(techniques_dir / "canyon-specialist.md") not in files
    assert canyon["techniques"]["mateship"]["config"]["path"] == str(
        techniques_dir / "mateship.md"
    )
    assert canyon["techniques"]["canyon-specialist"]["config"]["path"] == str(
        techniques_dir / "canyon-specialist.md"
    )
