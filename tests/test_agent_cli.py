"""Tests for portable persistent-agent maintenance commands."""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from marianne_compiler.agent_cli import app
from marianne_compiler.identity import IdentitySeeder

runner = CliRunner()


def test_reconcile_command_dry_run_is_read_only(tmp_path: Path) -> None:
    agents = tmp_path / "agents"
    seeder = IdentitySeeder(agents)
    initial = {
        "name": "canyon",
        "seed_version": "1.0.0",
        "voice": "Structure persists.",
        "focus": "architecture",
        "role": "architect",
    }
    seeder.seed(initial)
    seed_path = tmp_path / "seed.yaml"
    seed_path.write_text(
        yaml.safe_dump({**initial, "seed_version": "2.0.0", "role": "co-composer"})
    )
    before = {
        path.relative_to(agents): path.read_bytes()
        for path in agents.rglob("*")
        if path.is_file()
    }

    result = runner.invoke(
        app,
        ["reconcile", str(seed_path), "--agents-dir", str(agents), "--dry-run"],
    )

    after = {
        path.relative_to(agents): path.read_bytes()
        for path in agents.rglob("*")
        if path.is_file()
    }
    assert result.exit_code == 0, result.output
    assert "would_update" in result.output
    assert before == after


def test_census_command_emits_read_only_report(tmp_path: Path) -> None:
    agents = tmp_path / "agents"
    IdentitySeeder(agents).seed(
        {"name": "canyon", "voice": "v", "focus": "f"}
    )

    result = runner.invoke(
        app,
        ["census", "--canonical-root", str(agents), "--search-root", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    report = yaml.safe_load(result.output)
    assert report["mode"] == "read_only"
    assert report["canonical"][0]["agent_id"] == "canyon"


def test_bind_score_routes_refuses_overwriting_managed_source(tmp_path: Path) -> None:
    score = tmp_path / "score.yaml"
    score.write_text("name: score\n")
    inventory = tmp_path / "inventory.yaml"
    inventory.write_text("profiles: []\n")

    result = runner.invoke(
        app,
        [
            "bind-score-routes",
            str(score),
            str(inventory),
            "--output",
            str(score),
        ],
    )

    assert result.exit_code != 0
    assert "separate run artifact" in result.output
