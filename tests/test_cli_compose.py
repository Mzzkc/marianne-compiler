"""Tests for the compose CLI command (mzt compose).

Validates that the CLI reads config, produces score files, handles
fleet generation, and produces clear errors for invalid input.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

runner = CliRunner()


def _create_config(tmp_path: Path) -> Path:
    """Create a minimal compose config for testing."""
    config = {
        "project": {"name": "test-project", "workspace": str(tmp_path / "workspace")},
        "defaults": {
            "instruments": {
                "work": {
                    "primary": {"instrument": "openrouter", "model": "test-model"},
                },
            },
        },
        "agents": [
            {
                "name": "test-agent",
                "voice": "Testing voice.",
                "focus": "testing",
                "role": "tester",
            },
        ],
    }
    config_path = tmp_path / "test-config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)
    return config_path


def _create_multi_agent_config(tmp_path: Path) -> Path:
    """Create a multi-agent compose config for testing."""
    config = {
        "project": {"name": "multi-project", "workspace": str(tmp_path / "workspace")},
        "defaults": {},
        "agents": [
            {"name": "agent-a", "voice": "Voice A.", "focus": "focus-a"},
            {"name": "agent-b", "voice": "Voice B.", "focus": "focus-b"},
        ],
    }
    config_path = tmp_path / "multi-config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)
    return config_path


def _make_app():  # type: ignore[no-untyped-def]
    """Create a Typer app with compose command registered."""
    import typer

    from marianne_compiler.cli import compose

    app = typer.Typer()
    app.command()(compose)
    return app


class TestCliCompose:
    """Tests for the compose CLI command."""

    def test_reads_config_produces_scores(self, tmp_path: Path) -> None:
        """Compose reads config and produces score files."""
        app = _make_app()
        config_path = _create_config(tmp_path)
        output_dir = tmp_path / "scores"
        agents_dir = tmp_path / "agents"

        result = runner.invoke(app, [
            str(config_path),
            "--output", str(output_dir),
            "--agents-dir", str(agents_dir),
        ])

        assert result.exit_code == 0, f"Exit code: {result.exit_code}\n{result.output}"
        assert (output_dir / "test-agent.yaml").exists()

        # Verify generated score is valid YAML with expected structure
        score_data = yaml.safe_load((output_dir / "test-agent.yaml").read_text())
        assert isinstance(score_data, dict)
        assert "name" in score_data
        assert "sheet" in score_data
        assert "prompt" in score_data
        assert score_data["sheet"]["total_items"] == 12

        hook = score_data["on_success"][0]
        score_path = output_dir / "test-agent.yaml"
        assert hook["job_path"] == str(score_path.resolve())
        assert Path(hook["job_path"]).exists()

    def test_default_output_uses_workspace_scores_dir(self, tmp_path: Path) -> None:
        """When workspace is configured, default output is workspace/scores."""
        app = _make_app()
        config_path = _create_config(tmp_path)
        agents_dir = tmp_path / "agents"
        output_dir = tmp_path / "workspace" / "scores"

        result = runner.invoke(app, [
            str(config_path),
            "--agents-dir", str(agents_dir),
        ])

        assert result.exit_code == 0, f"Exit code: {result.exit_code}\n{result.output}"
        score_path = output_dir / "test-agent.yaml"
        assert score_path.exists()

        score_data = yaml.safe_load(score_path.read_text())
        assert score_data["on_success"][0]["job_path"] == (
            "{workspace}/scores/test-agent.yaml"
        )

    def test_fleet_flag_produces_fleet_config(self, tmp_path: Path) -> None:
        """--fleet flag forces fleet config generation even for single agent."""
        app = _make_app()
        config_path = _create_config(tmp_path)
        output_dir = tmp_path / "scores"
        agents_dir = tmp_path / "agents"

        result = runner.invoke(app, [
            str(config_path),
            "--output", str(output_dir),
            "--agents-dir", str(agents_dir),
            "--fleet",
        ])

        assert result.exit_code == 0, f"Exit code: {result.exit_code}\n{result.output}"
        assert (output_dir / "fleet.yaml").exists()

        fleet_data = yaml.safe_load((output_dir / "fleet.yaml").read_text())
        assert isinstance(fleet_data, dict)
        assert fleet_data.get("type") == "fleet"
        assert "scores" in fleet_data

    def test_invalid_config_produces_clear_error(self, tmp_path: Path) -> None:
        """Malformed YAML produces a clear error message."""
        app = _make_app()

        config_path = tmp_path / "bad.yaml"
        config_path.write_text(":\n  - [\ninvalid yaml content")

        result = runner.invoke(app, [str(config_path)])
        assert result.exit_code != 0

    def test_missing_config_produces_clear_error(self, tmp_path: Path) -> None:
        """Non-existent config file produces a clear error message."""
        app = _make_app()

        result = runner.invoke(app, [str(tmp_path / "nonexistent.yaml")])
        assert result.exit_code != 0

    def test_empty_agents_fails(self, tmp_path: Path) -> None:
        """Config with no agents exits with error."""
        app = _make_app()

        config_path = tmp_path / "empty.yaml"
        config_path.write_text("project:\n  name: empty\nagents: []\n")

        result = runner.invoke(app, [str(config_path)])
        assert result.exit_code != 0

    def test_dry_run(self, tmp_path: Path) -> None:
        """--dry-run shows summary without generating files."""
        app = _make_app()
        config_path = _create_config(tmp_path)

        result = runner.invoke(app, [str(config_path), "--dry-run"])

        assert result.exit_code == 0
        assert "test-project" in result.output or "Dry Run" in result.output

    def test_preset_dry_run(self) -> None:
        """--preset loads a shipped compiler config without a config path."""
        app = _make_app()

        result = runner.invoke(app, ["--preset", "generic-fleet", "--dry-run"])

        assert result.exit_code == 0
        assert "generic-agent-fleet" in result.output
        assert "Agents: 32" in result.output

    def test_seed_only(self, tmp_path: Path) -> None:
        """--seed-only creates identities without scores."""
        app = _make_app()
        config_path = _create_config(tmp_path)
        agents_dir = tmp_path / "agents"

        result = runner.invoke(app, [
            str(config_path),
            "--seed-only",
            "--agents-dir", str(agents_dir),
        ])

        assert result.exit_code == 0
        assert (agents_dir / "test-agent" / "identity.md").exists()
        assert (agents_dir / "test-agent" / "profile.yaml").exists()

    def test_multi_agent_generates_fleet(self, tmp_path: Path) -> None:
        """Multiple agents auto-generate a fleet config."""
        app = _make_app()
        config_path = _create_multi_agent_config(tmp_path)
        output_dir = tmp_path / "scores"
        agents_dir = tmp_path / "agents"

        result = runner.invoke(app, [
            str(config_path),
            "--output", str(output_dir),
            "--agents-dir", str(agents_dir),
        ])

        assert result.exit_code == 0
        assert (output_dir / "agent-a.yaml").exists()
        assert (output_dir / "agent-b.yaml").exists()
        assert (output_dir / "fleet.yaml").exists()

    def test_generated_score_has_valid_structure(self, tmp_path: Path) -> None:
        """Generated score has all expected top-level keys."""
        app = _make_app()
        config_path = _create_config(tmp_path)
        output_dir = tmp_path / "scores"
        agents_dir = tmp_path / "agents"

        runner.invoke(app, [
            str(config_path),
            "--output", str(output_dir),
            "--agents-dir", str(agents_dir),
        ])

        score_data = yaml.safe_load((output_dir / "test-agent.yaml").read_text())
        assert "name" in score_data
        assert "sheet" in score_data
        assert "prompt" in score_data
        assert score_data["sheet"]["total_items"] == 12
