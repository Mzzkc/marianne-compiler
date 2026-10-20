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


def _installed_agent(tmp_path: Path, shape: str) -> tuple[Path, Path]:
    agents = tmp_path / "agents"
    scores = agents / "canyon" / "scores"
    scores.mkdir(parents=True)
    score = {
        "name": f"{shape}-canyon",
        "workspace": "/REQUIRES-LIVE-BINDING",
        "instrument": "stale",
        "instrument_fallbacks": [],
        "sheet": {"per_sheet_instruments": {}, "per_sheet_fallbacks": {}},
        "prompt": {
            "variables": {
                "marianne_agent": {
                    "schema_version": 1,
                    "agent_id": "canyon",
                    "score_shape": shape,
                    "phase_requirements": {
                        "work": {"required_capabilities": ["file_editing"], "load_bearing": True}
                    },
                    "routing_receipts": {},
                }
            }
        },
    }
    (scores / f"{shape}.yaml").write_text(yaml.safe_dump(score, sort_keys=False))
    inventory = tmp_path / "inventory.yaml"
    inventory.write_text(yaml.safe_dump({
        "schema_version": 1,
        "profiles": [{
            "name": "verified", "provider": "anthropic", "model": "claude-opus-5-5",
            "available": True, "invocation_contract_verified": True,
            "entitlement_verified": True, "verified_at": "2026-10-20T00:00:00Z",
            "capabilities": ["file_editing"], "context_tokens": 200000,
            "reliability_class": "high", "latency_class": "normal",
            "metered_cost": "subscription", "priority": 1,
            "evidence": ["2026-10-20T00:00:00Z checked"],
        }],
    }))
    return agents, inventory


def test_engage_binds_names_and_workspaces_in_one_step(tmp_path: Path) -> None:
    agents, inventory = _installed_agent(tmp_path, "full-lifecycle")
    runs = tmp_path / "runs"
    result = runner.invoke(app, [
        "engage", "canyon", "--purpose", "Morning-Cut", "--inventory", str(inventory),
        "--runs-dir", str(runs), "--agents-dir", str(agents), "--date", "20261020",
        "--evidence-at", "2026-10-20T10:00:00Z",
    ])
    assert result.exit_code == 0, result.output
    engagement = runs / "canyon-morning-cut-20261020"
    output = engagement / "full-lifecycle-canyon-morning-cut-20261020.yaml"
    assert output.is_file()
    bound = yaml.safe_load(output.read_text())
    assert bound["name"] == "full-lifecycle-canyon-morning-cut-20261020"
    assert bound["workspace"] == str(engagement)
    assert bound["instrument"] == "verified--claude-opus-5-5" or "verified" in bound["instrument"]
    assert f"run: mzt run {output}" in result.output
    # The installed score is untouched.
    installed = yaml.safe_load((agents / "canyon" / "scores" / "full-lifecycle.yaml").read_text())
    assert installed["instrument"] == "stale"
    # A second engage with the same purpose on the same day is refused, not overwritten.
    again = runner.invoke(app, [
        "engage", "canyon", "--purpose", "morning-cut", "--inventory", str(inventory),
        "--runs-dir", str(runs), "--agents-dir", str(agents), "--date", "20261020",
    ])
    assert again.exit_code != 0
    assert "already bound" in again.output


def test_engage_targeted_work_needs_explicit_deferral(tmp_path: Path) -> None:
    agents, inventory = _installed_agent(tmp_path, "targeted-work")
    runs = tmp_path / "runs"
    base = [
        "engage", "canyon", "--purpose", "fix", "--inventory", str(inventory),
        "--runs-dir", str(runs), "--agents-dir", str(agents), "--shape", "targeted-work",
    ]
    refused = runner.invoke(app, base)
    assert refused.exit_code != 0
    assert "--defer-lifecycle" in refused.output
    assert not runs.exists()
    accepted = runner.invoke(app, [*base, "--defer-lifecycle"])
    assert accepted.exit_code == 0, accepted.output
    assert "lifecycle-integration afterwards" in accepted.output


def test_engage_default_shape_is_full_lifecycle_and_missing_score_is_named(tmp_path: Path) -> None:
    agents, inventory = _installed_agent(tmp_path, "targeted-work")  # no full-lifecycle installed
    result = runner.invoke(app, [
        "engage", "canyon", "--purpose", "x", "--inventory", str(inventory),
        "--runs-dir", str(tmp_path / "runs"), "--agents-dir", str(agents),
    ])
    assert result.exit_code != 0
    assert "full-lifecycle" in result.output and "install-package" in result.output
