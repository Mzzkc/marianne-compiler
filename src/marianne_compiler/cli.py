"""CLI entry point for the composition compiler.

Provides the ``compose`` command that both ``mzt compile`` and compiler
tests use. Takes a semantic agent config YAML and produces Marianne
score files via the CompilationPipeline.

Usage::

    mzt compile config.yaml --output scores/ --agents-dir ~/.marianne/agents/
    mzt compile config.yaml --dry-run
    mzt compile config.yaml --seed-only --agents-dir ~/.marianne/agents/
"""

from __future__ import annotations

from pathlib import Path

import typer
import yaml

from marianne_compiler.pipeline import CompilationPipeline
from marianne_compiler.presets import load_builtin_preset, prepare_builtin_preset


def compose(
    config: Path | None = typer.Argument(
        None,
        help="Path to the compiler config YAML file.",
    ),
    preset: str | None = typer.Option(
        None,
        "--preset",
        help="Built-in compiler preset to use, such as 'generic-fleet'.",
    ),
    workspace: Path | None = typer.Option(
        None,
        "--workspace",
        help=(
            "Workspace for a built-in preset. Defaults to "
            ".marianne/workspaces/<preset> under the current directory."
        ),
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output directory for generated score files. "
        "Defaults to <workspace>/scores when workspace is configured, "
        "otherwise scores/ next to the config file.",
    ),
    agents_dir: Path | None = typer.Option(
        None,
        "--agents-dir",
        help="Directory for agent identity stores. "
        "Defaults to ~/.marianne/agents/.",
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
    pause_before_chain: bool = typer.Option(
        False,
        "--pause-before-chain",
        help=(
            "Emit generated on_success hooks that pause before starting the "
            "next self-chain cycle."
        ),
    ),
    job_prefix: str | None = typer.Option(
        None,
        "--job-prefix",
        help=(
            "Prefix generated score filenames and conductor job IDs, while "
            "leaving agent identity names unchanged."
        ),
    ),
) -> None:
    """Compile semantic agent definitions into Marianne scores.

    Reads a YAML config that defines agents as people (voice, focus,
    techniques, instruments) and produces complete Marianne score YAML
    for each agent, plus identity directories and fleet configs.
    """
    # Load and validate config
    if preset:
        try:
            config_data = prepare_builtin_preset(
                load_builtin_preset(preset),
                name=preset,
                cwd=Path.cwd(),
                workspace=workspace,
            )
        except Exception as e:
            typer.echo(f"Error: Cannot load preset '{preset}': {e}", err=True)
            raise typer.Exit(code=1) from None
        config_base = Path.cwd()
        config_name = preset
    else:
        if config is None:
            typer.echo("Error: Provide a config path or --preset.", err=True)
            raise typer.Exit(code=1)
        if not config.exists() or not config.is_file():
            typer.echo(f"Error: Cannot read {config}", err=True)
            raise typer.Exit(code=1)
        try:
            with open(config) as f:
                config_data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            typer.echo(f"Error: Invalid YAML in {config}: {e}", err=True)
            raise typer.Exit(code=1) from None
        except OSError as e:
            typer.echo(f"Error: Cannot read {config}: {e}", err=True)
            raise typer.Exit(code=1) from None
        config_base = config.parent
        config_name = config.stem

    if pause_before_chain:
        defaults = config_data.setdefault("defaults", {})
        if isinstance(defaults, dict):
            defaults["pause_before_chain"] = True
    if job_prefix:
        defaults = config_data.setdefault("defaults", {})
        if isinstance(defaults, dict):
            defaults["job_name_prefix"] = job_prefix

    agents = config_data.get("agents", [])
    if not agents:
        typer.echo("Error: Config must contain at least one agent.", err=True)
        raise typer.Exit(code=1)

    project = config_data.get("project", {})
    project_name = project.get("name", config_name)
    workspace_path = CompilationPipeline._configured_workspace(
        config_data,
        base_dir=config_base,
    )
    default_output = (
        Path(workspace_path) / "scores" if workspace_path else config_base / "scores"
    )

    # Dry run — show summary and exit
    if dry_run:
        typer.echo(f"Dry Run: {project_name}")
        typer.echo(f"  Agents: {len(agents)}")
        for agent in agents:
            name = agent.get("name", "unnamed")
            focus = agent.get("focus", "")
            typer.echo(f"    - {name} ({focus})")
        typer.echo(f"  Output: {output or default_output}")
        typer.echo(f"  Fleet: {'yes' if fleet or len(agents) > 1 else 'no'}")
        raise typer.Exit(code=0)

    # Resolve directories. Workspace-local scores can use portable
    # {workspace}/... self-chain hooks; fall back to config-local scores
    # only when no workspace is configured.
    output_dir = output or default_output
    resolved_agents_dir = agents_dir or Path.home() / ".marianne" / "agents"

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
        score_paths = pipeline.compile_config(config_data, output_dir, base_dir=config_base)
    except Exception as e:
        typer.echo(f"Error: Compilation failed: {e}", err=True)
        raise typer.Exit(code=1) from None

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
