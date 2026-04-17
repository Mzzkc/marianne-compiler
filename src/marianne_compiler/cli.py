"""CLI entry point for the composition compiler.

Provides the ``compose`` command that both ``mzt compile`` and compiler
tests use. Takes a semantic agent config YAML and produces Marianne
score files via the CompilationPipeline.

Usage::

    mzt compile config.yaml --output scores/ --agents-dir ~/.mzt/agents/
    mzt compile config.yaml --dry-run
    mzt compile config.yaml --seed-only --agents-dir ~/.mzt/agents/
"""

from __future__ import annotations

from pathlib import Path

import typer
import yaml

from marianne_compiler.pipeline import CompilationPipeline


def compose(
    config: Path = typer.Argument(
        ...,
        help="Path to the compiler config YAML file.",
        exists=True,
        readable=True,
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output directory for generated score files. "
        "Defaults to scores/ next to the config file.",
    ),
    agents_dir: Path | None = typer.Option(
        None,
        "--agents-dir",
        help="Directory for agent identity stores. "
        "Defaults to ~/.mzt/agents/.",
    ),
    fleet: bool = typer.Option(
        False,
        "--fleet",
        help="Force fleet config generation even for a single agent.",
    ),
    seed_only: bool = typer.Option(
        False,
        "--seed-only",
        help="Create agent identity stores without generating scores.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show compilation summary without writing files.",
    ),
) -> None:
    """Compile semantic agent definitions into Marianne scores.

    Reads a YAML config that defines agents as people (voice, focus,
    techniques, instruments) and produces complete Marianne score YAML
    for each agent, plus identity directories and fleet configs.
    """
    # Load and validate config
    try:
        with open(config) as f:
            config_data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        typer.echo(f"Error: Invalid YAML in {config}: {e}", err=True)
        raise typer.Exit(code=1)
    except OSError as e:
        typer.echo(f"Error: Cannot read {config}: {e}", err=True)
        raise typer.Exit(code=1)

    agents = config_data.get("agents", [])
    if not agents:
        typer.echo("Error: Config must contain at least one agent.", err=True)
        raise typer.Exit(code=1)

    project = config_data.get("project", {})
    project_name = project.get("name", config.stem)

    # Dry run — show summary and exit
    if dry_run:
        typer.echo(f"Dry Run: {project_name}")
        typer.echo(f"  Agents: {len(agents)}")
        for agent in agents:
            name = agent.get("name", "unnamed")
            focus = agent.get("focus", "")
            typer.echo(f"    - {name} ({focus})")
        typer.echo(f"  Output: {output or 'scores/'}")
        typer.echo(f"  Fleet: {'yes' if fleet or len(agents) > 1 else 'no'}")
        raise typer.Exit(code=0)

    # Resolve directories
    output_dir = output or (config.parent / "scores")
    resolved_agents_dir = agents_dir or Path.home() / ".mzt" / "agents"

    # Create pipeline
    pipeline = CompilationPipeline(agents_dir=resolved_agents_dir)

    # Seed-only mode — create identities without scores
    if seed_only:
        for agent_def in agents:
            identity_path = pipeline.seed_identity(agent_def, resolved_agents_dir)
            typer.echo(f"Seeded identity: {identity_path}")
        raise typer.Exit(code=0)

    # Full compilation
    try:
        score_paths = pipeline.compile_config(config_data, output_dir)
    except Exception as e:
        typer.echo(f"Error: Compilation failed: {e}", err=True)
        raise typer.Exit(code=1)

    # Force fleet generation for single agent if --fleet flag set
    if fleet and len(agents) == 1:
        from marianne_compiler.fleet import FleetGenerator

        fleet_path = output_dir / "fleet.yaml"
        if not fleet_path.exists():
            FleetGenerator().write(config_data, output_dir, fleet_path)
            score_paths.append(fleet_path)

    for path in score_paths:
        typer.echo(f"Generated: {path}")

    typer.echo(
        f"Compiled {len(agents)} agent(s) to {output_dir}"
    )
