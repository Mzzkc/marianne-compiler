"""CLI for portable persistent-agent lifecycle and package maintenance."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
import yaml

from marianne_compiler.agent_package import generate_agent_package, install_agent_package
from marianne_compiler.capabilities import (
    bind_config_to_capabilities,
    bind_score_to_capabilities,
)
from marianne_compiler.identity import DEFAULT_AGENTS_DIR, IdentitySeeder
from marianne_compiler.memory_census import census_agent_memory

app = typer.Typer(
    name="marianne-agents",
    help="Safely reconcile, inspect, and package persistent Marianne agents.",
    no_args_is_help=True,
)


@app.command("reconcile")
def reconcile_command(
    seed: Path = typer.Argument(..., help="Portable agent seed YAML."),
    agents_dir: Path = typer.Option(
        DEFAULT_AGENTS_DIR,
        "--agents-dir",
        help="Canonical box-local agent data root.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing."),
) -> None:
    """Initialize or three-way reconcile one portable seed."""
    agent_def = _load_mapping(seed, "seed")
    seeder = IdentitySeeder(agents_dir)
    name = str(agent_def.get("name", ""))
    if not name:
        raise typer.BadParameter("seed must contain name")
    agent_dir = agents_dir / name
    if not agent_dir.exists() and not dry_run:
        seeder.seed(agent_def)
        payload: dict[str, Any] = {
            "agent_dir": str(agent_dir),
            "status": "initialized",
            "seed_version": str(agent_def.get("seed_version", "1.0.0")),
            "actions": ["initialized L1-L4 and portable baseline"],
            "conflicts": [],
        }
    else:
        result = seeder.reconcile(agent_def, dry_run=dry_run)
        payload = {
            "agent_dir": str(result.agent_dir),
            "status": result.status,
            "seed_version": result.seed_version,
            "actions": list(result.actions),
            "conflicts": list(result.conflicts),
            "receipt_path": str(result.receipt_path) if result.receipt_path else None,
        }
    typer.echo(yaml.safe_dump(payload, sort_keys=False).rstrip())


@app.command("acknowledge")
def acknowledge_command(
    agent_name: str = typer.Argument(...),
    resolution: Path = typer.Argument(..., help="Agent-authored resolution YAML."),
    agents_dir: Path = typer.Option(DEFAULT_AGENTS_DIR, "--agents-dir"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Close seed conflict debt from an explicit agent adjudication."""
    document = _load_mapping(resolution, "resolution")
    receipt = IdentitySeeder(agents_dir).acknowledge_resolution(
        agent_name,
        document,
        dry_run=dry_run,
    )
    payload = {
        "status": "would_acknowledge" if dry_run else "acknowledged",
        "receipt_path": str(receipt),
    }
    typer.echo(yaml.safe_dump(payload, sort_keys=False).rstrip())


@app.command("census")
def census_command(
    canonical_root: Path = typer.Option(
        DEFAULT_AGENTS_DIR,
        "--canonical-root",
        help="Authoritative agent identity/memory root.",
    ),
    search_root: list[Path] = typer.Option(
        [],
        "--search-root",
        help="Additional root to scan; repeat for multiple roots.",
    ),
    output: Path | None = typer.Option(None, "--output", help="Optional report path."),
) -> None:
    """Report canonical, aliased, snapshot, and unknown memory trees read-only."""
    report = census_agent_memory(
        canonical_root=canonical_root,
        search_roots=search_root,
    )
    rendered = yaml.safe_dump(report, sort_keys=False)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered)
        typer.echo(str(output))
    else:
        typer.echo(rendered.rstrip())


@app.command("package")
def package_command(
    config: Path = typer.Argument(..., help="Compiler fleet config YAML."),
    output: Path = typer.Option(..., "--output", help="Agent-package output root."),
    techniques_dir: Path = typer.Option(..., "--techniques-dir"),
) -> None:
    """Generate seeds and three concrete score shapes for every cast member."""
    config_data = _load_mapping(config, "config")
    paths = generate_agent_package(
        config_data,
        output,
        techniques_dir=techniques_dir,
    )
    typer.echo(
        yaml.safe_dump(
            {"status": "generated", "file_count": len(paths), "output": str(output)},
            sort_keys=False,
        ).rstrip()
    )


@app.command("install-package")
def install_package_command(
    package_dir: Path = typer.Argument(..., help="Generated agent-package root."),
    techniques_source: Path = typer.Option(..., "--techniques-source"),
    agents_dir: Path = typer.Option(DEFAULT_AGENTS_DIR, "--agents-dir"),
    techniques_dir: Path = typer.Option(
        Path.home() / ".marianne" / "techniques",
        "--techniques-dir",
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Reconcile seeds and conservatively install scores/cadenzas/techniques."""
    report = install_agent_package(
        package_dir,
        techniques_source=techniques_source,
        agents_dir=agents_dir,
        techniques_dir=techniques_dir,
        dry_run=dry_run,
    )
    typer.echo(yaml.safe_dump(report, sort_keys=False).rstrip())


@app.command("bind-routes")
def bind_routes_command(
    config: Path = typer.Argument(...),
    inventory: Path = typer.Argument(...),
    output: Path = typer.Option(..., "--output"),
    evidence_at: str | None = typer.Option(None, "--evidence-at", hidden=True),
) -> None:
    """Bind semantic phase requirements to a verified capability inventory."""
    config_data = _load_mapping(config, "config")
    inventory_data = _load_mapping(inventory, "inventory")
    now = _parse_time(evidence_at) if evidence_at else datetime.now(UTC)
    bound = bind_config_to_capabilities(config_data, inventory_data, now=now)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(bound, sort_keys=False, allow_unicode=True))
    typer.echo(str(output))


@app.command("bind-score-routes")
def bind_score_routes_command(
    score: Path = typer.Argument(..., help="Concrete compiled agent score YAML."),
    inventory: Path = typer.Argument(..., help="Live-verified capability inventory."),
    output: Path = typer.Option(..., "--output"),
    workspace: Path | None = typer.Option(
        None,
        "--workspace",
        help="Fresh engagement workspace; defaults beside --output.",
    ),
    evidence_at: str | None = typer.Option(None, "--evidence-at", hidden=True),
) -> None:
    """Bind an installed runnable score directly to current route evidence."""
    if output.expanduser().resolve() == score.expanduser().resolve():
        raise typer.BadParameter(
            "--output must be a separate run artifact; do not overwrite the managed score"
        )
    score_data = _load_mapping(score, "score")
    inventory_data = _load_mapping(inventory, "inventory")
    now = _parse_time(evidence_at) if evidence_at else datetime.now(UTC)
    run_workspace = workspace or output.with_suffix("").with_name(
        f"{output.stem}-workspace"
    )
    bound = bind_score_to_capabilities(
        score_data,
        inventory_data,
        run_workspace=run_workspace,
        now=now,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(bound, sort_keys=False, allow_unicode=True))
    typer.echo(str(output))


def _load_mapping(path: Path, label: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise typer.BadParameter(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise typer.BadParameter(f"{label} must contain a YAML mapping")
    return value


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


if __name__ == "__main__":
    app()
