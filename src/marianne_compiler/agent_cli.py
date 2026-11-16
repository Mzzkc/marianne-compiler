"""CLI for portable persistent-agent lifecycle and package maintenance."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
import yaml

from marianne_compiler.agent_package import (
    SCORE_SHAPES,
    generate_agent_package,
    install_agent_package,
)
from marianne_compiler.capabilities import (
    MAX_TIMEOUT_SECONDS,
    bind_config_to_capabilities,
    bind_score_to_capabilities,
    localize_home_path,
)
from marianne_compiler.identity import DEFAULT_AGENTS_DIR, IdentitySeeder
from marianne_compiler.memory_census import census_agent_memory
from marianne_compiler.portable_paths import portabilize_score

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
    identity_dir = (
        bound.get("prompt", {}).get("variables", {}).get("agent_identity_dir")
        if isinstance(bound.get("prompt"), dict)
        else None
    )
    if isinstance(identity_dir, str) and identity_dir.strip():
        bound, path_warnings = portabilize_score(
            bound, Path(identity_dir).expanduser().parent
        )
        for warning in path_warnings:
            _echo_both(f"WARNING: {warning}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(bound, sort_keys=False, allow_unicode=True))
    typer.echo(str(output))


_DEFAULT_SHAPE = "full-lifecycle"
_DEFERRING_SHAPE = "targeted-work"
_DEBT_REFUSAL_THRESHOLD = 3

# Debt records are agent-authored and their shape drifted: a record carries the
# engagements it superseded under one of these keys (a list of engagement names,
# or one snapshot/archive pointer to a prior record).
_CARRIED_LIST_KEYS = ("carried_pending_from",)
_CARRIED_SINGLE_KEYS = (
    "carried_prior_debt",
    "prior_debt",
    "prior_debt_snapshot",
    "prior_debt_path",
    "prior_debt_archive",
    "prior_lifecycle_debt",
    "prior_lifecycle_debt_snapshot",
    "prior_pending_debt_snapshot",
    "prior_record_snapshot",
)


@app.command("engage")
def engage_command(
    agent: str = typer.Argument(..., help="Installed agent id (directory under --agents-dir)."),
    purpose: str = typer.Option(
        ..., "--purpose", "-p",
        help="Short slug for this engagement (letters, digits, '-'); part of the job name.",
    ),
    inventory: Path = typer.Option(
        ..., "--inventory", "-i", help="Live-verified capability inventory YAML.",
    ),
    runs_dir: Path = typer.Option(
        ..., "--runs-dir", "-r",
        help="Directory that receives one sub-directory per engagement (score + receipts).",
    ),
    shape: str = typer.Option(
        _DEFAULT_SHAPE, "--shape", "-s",
        help="full-lifecycle (default) | targeted-work | lifecycle-integration.",
    ),
    defer_lifecycle: bool = typer.Option(
        False, "--defer-lifecycle",
        help="Required with --shape targeted-work: acknowledges that consolidate, "
        "reflect, maturity and resurrect become pending debt a lifecycle-integration "
        "engagement must pay back.",
    ),
    accept_debt: bool = typer.Option(
        False, "--accept-debt",
        help="Proceed with --shape targeted-work although the agent already has "
        f"{_DEBT_REFUSAL_THRESHOLD}+ pending lifecycle debts. Debt compounds: pay it "
        "with a lifecycle-integration engagement first unless you can say why not.",
    ),
    task: Path | None = typer.Option(
        None, "--task", "-t",
        help="Task file for this engagement. It is copied (read-only) into the "
        "engagement run directory and injected as a REQUIRED prelude item reaching "
        "every sheet; its sha256 is recorded in the bound score's marianne_agent "
        "contract. Prefer this over appending to an agent's cadenza files.",
    ),
    step_timeout: int | None = typer.Option(
        None, "--step-timeout",
        help="Per-attempt limit in seconds for every LLM sheet (primary and "
        f"fallbacks); 1..{MAX_TIMEOUT_SECONDS}. Applied inside the binder so routing "
        "receipts stay true; never edit a bound score to change it. The stock limit "
        "is 1800 s.",
    ),
    idle_timeout: int | None = typer.Option(
        None, "--idle-timeout",
        help="Seconds without workspace output before stale detection fails a "
        f"sheet; 1..{MAX_TIMEOUT_SECONDS}. Enables stale_detection.",
    ),
    workspaces_dir: Path | None = typer.Option(
        None, "--workspaces-dir", "-w",
        help="Root for the fresh engagement workspace; defaults to --runs-dir.",
    ),
    agents_dir: Path = typer.Option(
        DEFAULT_AGENTS_DIR, "--agents-dir", help="Canonical box-local agent data root.",
    ),
    date: str | None = typer.Option(None, "--date", hidden=True, help="YYYYMMDD override."),
    evidence_at: str | None = typer.Option(None, "--evidence-at", hidden=True),
) -> None:
    """Bind, name and workspace one engagement of an installed agent in one step.

    The reuse ladder's first rung for persistent agents: the installed score is
    read in place and never edited; the bound run artifact, the job name and the
    fresh workspace are derived from AGENT, --shape, --purpose and today's date,
    so every engagement is one command and nothing is hand-copied or hand-named.
    """
    if shape not in SCORE_SHAPES:
        raise typer.BadParameter(
            f"--shape must be one of: {', '.join(SCORE_SHAPES)}"
        )
    if shape == _DEFERRING_SHAPE and not defer_lifecycle:
        raise typer.BadParameter(
            "targeted-work defers consolidate, reflect, maturity and resurrect into "
            "pending lifecycle debt. Pass --defer-lifecycle to confirm, and plan the "
            "lifecycle-integration engagement that pays it back; otherwise use the "
            "default full-lifecycle shape."
        )
    slug = purpose.strip().lower()
    if not slug or not all(ch.isalnum() or ch == "-" for ch in slug):
        raise typer.BadParameter("--purpose must be a slug of letters, digits and '-'")
    agent_id = agent.strip()
    installed = agents_dir.expanduser().resolve() / agent_id / "scores" / f"{shape}.yaml"
    if not installed.is_file():
        raise typer.BadParameter(
            f"no installed {shape} score for agent {agent_id!r} at {installed}; "
            "run marianne-agents install-package first"
        )
    debt_count, debt_note = _pending_debt(agents_dir, agent_id)
    if shape == _DEFERRING_SHAPE and debt_count >= _DEBT_REFUSAL_THRESHOLD and not accept_debt:
        _echo_both(
            f"debt: REFUSED, {agent_id} already has {debt_count} pending lifecycle "
            f"debts{debt_note}"
        )
        raise typer.BadParameter(
            f"{agent_id} already has {debt_count} pending lifecycle debts{debt_note}; "
            "targeted-work would add another. Pay them first with: marianne-agents "
            f"engage {agent_id} --shape lifecycle-integration --purpose <slug> "
            "--inventory <inventory> --runs-dir <runs-dir>. Pass --accept-debt to "
            "defer again anyway."
        )
    stamp = date or datetime.now(UTC).strftime("%Y%m%d")
    engagement = f"{agent_id}-{slug}-{stamp}"
    job_name = f"{shape}-{engagement}"
    run_dir = runs_dir.expanduser().resolve() / engagement
    output = run_dir / f"{job_name}.yaml"
    run_workspace = (workspaces_dir or runs_dir).expanduser().resolve() / engagement
    if output.exists():
        raise typer.BadParameter(
            f"engagement already bound: {output}. One engagement is one directory; "
            "pick another --purpose or resume the existing job with mzt resume."
        )
    for flag, value in (("--step-timeout", step_timeout), ("--idle-timeout", idle_timeout)):
        if value is not None and not 0 < value <= MAX_TIMEOUT_SECONDS:
            raise typer.BadParameter(
                f"{flag} must be a positive integer of at most {MAX_TIMEOUT_SECONDS}"
            )
    task_source = _check_task_file(task) if task is not None else None
    score_data = _load_mapping(installed, "score")
    inventory_data = _load_mapping(inventory, "inventory")
    now = _parse_time(evidence_at) if evidence_at else datetime.now(UTC)
    bound = bind_score_to_capabilities(
        score_data, inventory_data, run_workspace=run_workspace, now=now,
        step_timeout_seconds=step_timeout, idle_timeout_seconds=idle_timeout,
    )
    bound["name"] = job_name
    bound, path_warnings = portabilize_score(bound, agents_dir)
    for warning in path_warnings:
        _echo_both(f"WARNING: {warning}")
    run_dir.mkdir(parents=True, exist_ok=True)
    task_line = None
    if task_source is not None:
        task_line = _attach_task(bound, task_source, run_dir)
    output.write_text(yaml.safe_dump(bound, sort_keys=False, allow_unicode=True))
    typer.echo(f"job: {job_name}")
    if task_line:
        typer.echo(task_line)
    typer.echo(f"score: {output}")
    for line in _workspace_lines(
        (workspaces_dir or runs_dir), engagement, run_workspace, run_dir,
    ):
        typer.echo(line)
    typer.echo(f"installed: {installed}")
    if shape == _DEFERRING_SHAPE:
        # Conductors pipe stderr away, so the debt line is on both streams.
        _echo_both(
            f"debt: {debt_count} pending before this run{debt_note}; targeted-work "
            f"leaves more. Engage {agent_id} with --shape lifecycle-integration "
            "afterwards"
        )
    elif debt_count:
        typer.echo(f"debt: {debt_count} pending{debt_note}")
    typer.echo(f"run: mzt run {output}")


def _filesystem(path: Path) -> tuple[int, str]:
    """(device id, mount point) of the nearest existing ancestor of ``path``."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    device = probe.stat().st_dev
    mount = probe
    while not mount.is_mount() and mount != mount.parent:
        mount = mount.parent
    return device, str(mount)


def _workspace_lines(
    requested_root: Path, engagement: str, real_workspace: Path, run_dir: Path,
) -> list[str]:
    """The resolved workspace, its filesystem, and a warning when a symlink hid a move.

    A workspace requested under a symlink that lands on another filesystem
    (e.g. a home directory that is a link onto a USB disk) silently changes
    where cycle-state and receipts live and how fast they are; say so.
    """
    device, mount = _filesystem(real_workspace)
    lines = [f"workspace: {real_workspace} (filesystem {mount})"]
    requested = Path(os.path.abspath(requested_root.expanduser())) / engagement
    if requested != real_workspace:
        runs_device, runs_mount = _filesystem(run_dir)
        if device != runs_device:
            lines.append(
                f"WARNING: workspace {requested} resolves through a symlink to "
                f"{real_workspace} on filesystem {mount}, which differs from the runs "
                f"dir's filesystem {runs_mount}; receipts and workspace will live on "
                "different disks."
            )
    return lines


def _echo_both(message: str) -> None:
    typer.echo(message)
    typer.echo(message, err=True)


def _pending_debt(agents_dir: Path, agent_id: str) -> tuple[int, str]:
    """Count the agent's pending lifecycle debts: (count, human note).

    The current record counts as one when its status is pending. Every
    engagement it names under ``carried_pending_from`` and every archived prior
    record it points at (followed while the snapshot exists on disk, cycle
    guarded) adds one. A record that cannot be read counts as the threshold:
    fail closed rather than hide debt.
    """
    path = (
        agents_dir.expanduser().resolve() / agent_id / ".marianne"
        / "pending-lifecycle-debt.yaml"
    )
    if not path.is_file():
        return 0, ""
    record = _read_debt(path)
    if record is None:
        return (
            _DEBT_REFUSAL_THRESHOLD,
            f" (debt record {path} is unreadable; counted conservatively)",
        )
    if str(record.get("status", "")).strip().lower() != "pending":
        return 0, ""
    count = 1
    seen: set[Path] = {path}
    queue = [record]
    while queue:
        current = queue.pop()
        for key in _CARRIED_LIST_KEYS:
            if isinstance(current.get(key), list):
                count += len(current[key])
        for key in _CARRIED_SINGLE_KEYS:
            embedded = current.get(key)
            if (
                isinstance(embedded, dict)
                and str(embedded.get("status", "")).lower() == "pending"
            ):
                count += 1  # prior record preserved verbatim inside this one
                queue.append(embedded)
                break
            target = _debt_pointer(embedded)
            if target is None:
                continue
            if target in seen or not target.is_file():
                if target not in seen and current.get(key):
                    count += 1  # named but archived off-box: still one prior debt
                    seen.add(target)
                continue
            seen.add(target)
            prior = _read_debt(target)
            if prior is None or str(prior.get("status", "pending")).lower() != "pending":
                continue
            count += 1
            queue.append(prior)
            break
    return count, f" (counted from {path}, following archived prior records)"


def _read_debt(path: Path) -> dict[str, Any] | None:
    try:
        value = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        return None
    return value if isinstance(value, dict) else None


def _debt_pointer(value: Any) -> Path | None:
    if isinstance(value, dict):
        value = value.get("path") or value.get("archive")
    if isinstance(value, str) and value.strip():
        return Path(value.strip()).expanduser()
    return None


def _check_task_file(task: Path) -> Path:
    source = task.expanduser().resolve()
    if not source.is_file():
        raise typer.BadParameter(f"--task {task} is not a readable file")
    if source.stat().st_size == 0:
        raise typer.BadParameter(f"--task {task} is empty")
    return source


def _attach_task(bound: dict[str, Any], source: Path, run_dir: Path) -> str:
    """Copy the task into the run dir (read-only) and inject it into every sheet.

    The copy, not the source, is what the sheets read, so later edits to the
    source cannot change what a running engagement was told. The sha256 goes
    into the marianne_agent contract, which already carries bind provenance.
    """
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    # The name is spliced into a Jinja path template, so keep it inert.
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", source.name)
    copy_name = f"task-{safe_name}"
    copy = run_dir / copy_name
    copy.write_bytes(data)
    os.chmod(copy, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    sheet = bound.setdefault("sheet", {})
    prelude = sheet.setdefault("prelude", [])
    if not isinstance(prelude, list):
        raise typer.BadParameter("score sheet.prelude must be a list to attach --task")
    # {{ score_dir }} is the bound score file's directory, rendered at run time
    # by the conductor; an absolute path here would fail V004 and tie the bound
    # score to this machine's home layout.
    prelude.append(
        {"file": f"{{{{ score_dir }}}}/{copy_name}", "as": "context", "required": True}
    )
    contract = bound["prompt"]["variables"]["marianne_agent"]
    contract["task"] = {
        "source": localize_home_path(str(source)),
        "copy": copy_name,
        "copy_relative_to": "score_dir",
        "sha256": f"sha256:{digest}",
    }
    return f"task: {source} sha256:{digest[:16]}"


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
