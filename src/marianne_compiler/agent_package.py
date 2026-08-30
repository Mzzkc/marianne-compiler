"""Generate portable, ready-to-bind score sets for persistent Marianne agents."""

from __future__ import annotations

import copy
import hashlib
import os
import shlex
import shutil
import tempfile
from importlib.resources import files
from pathlib import Path
from typing import Any, TypeAlias

import yaml

from marianne_compiler.identity import IdentitySeeder, validate_agent_id
from marianne_compiler.pipeline import CompilationPipeline

SCORE_SHAPES = ("full-lifecycle", "targeted-work", "lifecycle-integration")
AssetSource: TypeAlias = Path | bytes
_SEED_KEYS = (
    "name",
    "seed_version",
    "voice",
    "identity_voice",
    "focus",
    "role",
    "group",
    "meditation",
    "values",
    "standing_patterns",
    "identity_notes",
    "skills",
    "a2a_skills",
    "growth_axes",
    "compatibility",
    "relationships",
    "techniques",
)


def generate_agent_package(
    config: dict[str, Any],
    output_dir: Path,
    *,
    techniques_dir: Path,
) -> list[Path]:
    """Generate versioned seeds plus three concrete score shapes per person.

    Generated scores use public runtime locations below ``~/.marianne``. The
    compile itself uses isolated temporary state, so package generation never
    seeds or updates a real agent registry.
    """
    agents = config.get("agents", [])
    if not isinstance(agents, list) or not agents:
        raise ValueError("Agent package config must contain at least one agent")
    if not techniques_dir.is_dir():
        raise ValueError(f"Techniques directory does not exist: {techniques_dir}")

    prepared_agents: list[tuple[str, dict[str, Any]]] = []
    seen_agent_ids: set[str] = set()
    for agent_def in agents:
        if not isinstance(agent_def, dict) or not agent_def.get("name"):
            raise ValueError("Every packaged agent must be a named mapping")
        name = validate_agent_id(agent_def["name"])
        if name in seen_agent_ids:
            raise ValueError(f"duplicate agent id in package config: {name}")
        seen_agent_ids.add(name)
        prepared_agents.append((name, agent_def))

    published_output = output_dir.expanduser().resolve()
    published_output.parent.mkdir(parents=True, exist_ok=True)
    preserved_readme = _read_preserved_package_readme(published_output)
    generated: list[Path] = []
    roster_agents: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(
        prefix=f".{published_output.name}.build-",
        dir=published_output.parent,
    ) as raw_publish:
        output_dir = Path(raw_publish) / "package"
        output_dir.mkdir()
        with tempfile.TemporaryDirectory(prefix="marianne-agent-package-") as raw_temp:
            temp_root = Path(raw_temp)
            for name, agent_def in prepared_agents:
                seed = _portable_seed(agent_def)
                seed_path = output_dir / "seeds" / name / "seed.yaml"
                _write_yaml(seed_path, seed)
                generated.append(seed_path)
                cadenza_paths = _write_personal_cadenza_seed(output_dir, name)
                generated.extend(cadenza_paths)

                score_refs: dict[str, str] = {}
                score_paths: list[Path] = []
                for shape in SCORE_SHAPES:
                    scratch = temp_root / name / shape
                    score = _compile_shape(
                        config,
                        agent_def,
                        shape=shape,
                        scratch=scratch,
                        techniques_dir=techniques_dir,
                    )
                    public_agent_root = f"~/.marianne/agents/{name}"
                    replacements = {
                        "{{workspace}}/shared/active": (
                            f"{public_agent_root}/cadenzas/personal/active"
                        ),
                        str((scratch / "agents").resolve()): "~/.marianne/agents",
                        str(techniques_dir.resolve()): "~/.marianne/techniques",
                        str((scratch / "workspace").resolve()): (
                            f"{public_agent_root}/workspaces/{shape}"
                        ),
                    }
                    score = _replace_strings(score, replacements)
                    score["workspace"] = (
                        f"{public_agent_root}/workspaces/"
                        f"REQUIRES-LIVE-BINDING-{shape}"
                    )
                    score["description"] = (
                        f"{name.title()} persistent-agent {shape} engagement. "
                        "Bind phase routes from current live capability evidence before submission."
                    )
                    score_path = output_dir / "scores" / name / f"{shape}.yaml"
                    _write_yaml(score_path, score)
                    generated.append(score_path)
                    score_paths.append(score_path)
                    score_refs[shape.replace("-", "_")] = score_path.relative_to(
                        output_dir
                    ).as_posix()

                agent_assets = [seed_path, *cadenza_paths, *score_paths]
                roster_agents.append(
                    {
                        "id": name,
                        "seed_version": str(seed["seed_version"]),
                        "role": str(agent_def.get("role", "builder")),
                        "focus": str(agent_def.get("focus", "")),
                        "specialist_technique": f"{name}-specialist",
                        "scores": score_refs,
                        "asset_hashes": {
                            path.relative_to(output_dir).as_posix(): _hash_path(path)
                            for path in sorted(agent_assets)
                        },
                    }
                )

        roster = {
            "schema_version": 1,
            "kind": "marianne-persistent-agent-roster",
            "agent_data_root": "~/.marianne/agents",
            "technique_runtime_root": "~/.marianne/techniques",
            "routing_policy": "live-capability-evidence-required",
            "agents": roster_agents,
        }
        roster_path = output_dir / "roster.yaml"
        _write_yaml(roster_path, roster)
        generated.insert(0, roster_path)
        if preserved_readme is not None:
            _atomic_write_bytes(output_dir / "README.md", preserved_readme)
        relative_generated = [path.relative_to(output_dir) for path in generated]
        _publish_package_directory(output_dir, published_output)
    return [published_output / path for path in relative_generated]


def install_agent_package(
    package_dir: Path,
    *,
    techniques_source: Path,
    agents_dir: Path,
    techniques_dir: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Install a package without overwriting lived or locally changed data."""
    package_dir = package_dir.expanduser().resolve()
    techniques_source = techniques_source.expanduser().resolve()
    agents_dir = agents_dir.expanduser().resolve()
    techniques_dir = techniques_dir.expanduser().resolve()
    roster_path = package_dir / "roster.yaml"
    roster = yaml.safe_load(roster_path.read_text()) if roster_path.is_file() else None
    if not isinstance(roster, dict) or not isinstance(roster.get("agents"), list):
        raise ValueError(f"Invalid persistent-agent package roster: {roster_path}")
    if not techniques_source.is_dir():
        raise ValueError(f"Techniques source does not exist: {techniques_source}")

    package_agents_root = str(roster.get("agent_data_root", "~/.marianne/agents"))
    package_techniques_root = str(
        roster.get("technique_runtime_root", "~/.marianne/techniques")
    )
    prepared_agents: list[tuple[str, dict[str, Any], dict[str, AssetSource]]] = []
    seen_agent_ids: set[str] = set()
    for roster_agent in roster["agents"]:
        if not isinstance(roster_agent, dict) or not roster_agent.get("id"):
            raise ValueError("Every roster entry must contain an id")
        agent_name = validate_agent_id(roster_agent["id"])
        if agent_name in seen_agent_ids:
            raise ValueError(f"duplicate agent id in package roster: {agent_name}")
        seen_agent_ids.add(agent_name)
        seed_path = package_dir / "seeds" / agent_name / "seed.yaml"
        seed = yaml.safe_load(seed_path.read_text()) if seed_path.is_file() else None
        if not isinstance(seed, dict):
            raise ValueError(f"Invalid or missing agent seed: {seed_path}")
        seed_name = validate_agent_id(seed.get("name"))
        if seed_name != agent_name:
            raise ValueError(
                f"agent seed name {seed_name!r} does not match roster id {agent_name!r}"
            )
        roster_seed_version = str(roster_agent.get("seed_version", ""))
        seed_version = str(seed.get("seed_version", ""))
        if not roster_seed_version or roster_seed_version != seed_version:
            raise ValueError(
                f"agent seed version {seed_version!r} does not match roster "
                f"version {roster_seed_version!r} for {agent_name}"
            )
        agent_dir = agents_dir / agent_name
        if agent_dir.is_symlink():
            raise ValueError(f"Managed agent root must not be a symlink: {agent_dir}")
        asset_sources: dict[str, AssetSource] = {}
        cadenza_root = package_dir / "seeds" / agent_name / "cadenzas"
        if cadenza_root.is_dir():
            for source in sorted(cadenza_root.rglob("*")):
                if source.is_file():
                    relative = Path("cadenzas") / source.relative_to(cadenza_root)
                    asset_sources[relative.as_posix()] = source.read_bytes()
        score_root = package_dir / "scores" / agent_name
        if not score_root.is_dir():
            raise ValueError(f"Missing packaged score directory: {score_root}")
        for source in sorted(score_root.glob("*.yaml")):
            relative = Path("scores") / source.name
            try:
                score = yaml.safe_load(source.read_text())
            except yaml.YAMLError as exc:
                raise ValueError(f"Invalid packaged score: {source}: {exc}") from exc
            if not isinstance(score, dict):
                raise ValueError(f"Invalid packaged score: {source}")
            replacements = {
                f"{package_agents_root.rstrip('/')}/{agent_name}": str(agent_dir),
                package_techniques_root: str(techniques_dir),
            }
            localized = _localize_score(score, replacements)
            asset_sources[relative.as_posix()] = _yaml_bytes(localized)
        expected_scores = {f"scores/{shape}.yaml" for shape in SCORE_SHAPES}
        if not expected_scores.issubset(asset_sources):
            missing = ", ".join(sorted(expected_scores - set(asset_sources)))
            raise ValueError(f"Missing packaged scores for {agent_name}: {missing}")
        _verify_roster_asset_hashes(
            package_dir,
            roster_agent,
            agent_name=agent_name,
        )
        prepared_agents.append((agent_name, seed, asset_sources))

    technique_sources: dict[str, AssetSource] = {
        source.relative_to(techniques_source).as_posix(): source.read_bytes()
        for source in sorted(techniques_source.rglob("*.md"))
        if source.is_file()
    }

    actions: list[dict[str, str]] = []
    conflicts: list[dict[str, str]] = []
    seeder = IdentitySeeder(agents_dir)
    for agent_name, seed, asset_sources in prepared_agents:
        agent_dir = agents_dir / agent_name
        if dry_run:
            result = seeder.reconcile(seed, dry_run=True)
            actions.append({"path": str(agent_dir), "action": result.status})
        else:
            seeder.seed(seed)
            actions.append({"path": str(agent_dir), "action": "seed_reconciled"})

        workspaces_dir = agent_dir / "workspaces"
        _assert_managed_target(agent_dir, workspaces_dir)
        workspace_action = "unchanged" if workspaces_dir.is_dir() else (
            "would_create" if dry_run else "created"
        )
        if not dry_run:
            workspaces_dir.mkdir(parents=True, exist_ok=True)
        actions.append({"path": str(workspaces_dir), "action": workspace_action})

        synced = _sync_managed_assets(
            asset_sources,
            target_root=agent_dir,
            baseline_path=agent_dir / ".marianne" / "installed-package-assets.yaml",
            conflict_path=agent_dir / ".marianne" / "pending-package-asset-conflicts.yaml",
            dry_run=dry_run,
        )
        actions.extend(synced["actions"])
        conflicts.extend(synced["conflicts"])

    technique_sync = _sync_managed_assets(
        technique_sources,
        target_root=techniques_dir,
        baseline_path=techniques_dir / ".marianne-agent-package-baseline.yaml",
        conflict_path=techniques_dir / ".marianne-agent-package-conflicts.yaml",
        dry_run=dry_run,
    )
    actions.extend(technique_sync["actions"])
    conflicts.extend(technique_sync["conflicts"])
    return {
        "schema_version": 1,
        "status": "dry_run" if dry_run else "installed",
        "actions": actions,
        "conflicts": conflicts,
    }


def _compile_shape(
    config: dict[str, Any],
    agent_def: dict[str, Any],
    *,
    shape: str,
    scratch: Path,
    techniques_dir: Path,
) -> dict[str, Any]:
    shape_config = copy.deepcopy(config)
    shape_config["project"] = {
        **(
            shape_config.get("project", {})
            if isinstance(shape_config.get("project"), dict)
            else {}
        ),
        "workspace": str((scratch / "workspace").resolve()),
    }
    defaults = shape_config.setdefault("defaults", {})
    if not isinstance(defaults, dict):
        raise ValueError("Compiler defaults must be a mapping")
    defaults["score_shape"] = shape
    defaults["self_chain"] = False
    defaults["job_name_prefix"] = f"{shape}-"
    shared_workspace = defaults.setdefault("shared_workspace", {})
    if not isinstance(shared_workspace, dict):
        raise ValueError("defaults.shared_workspace must be a mapping")
    shared_workspace.update({"enabled": True, "seed": True})
    cadenzas = defaults.setdefault("cadenzas", {})
    if not isinstance(cadenzas, dict):
        raise ValueError("defaults.cadenzas must be a mapping")
    active_cadenzas = cadenzas.setdefault("active", [])
    if not isinstance(active_cadenzas, list):
        raise ValueError("defaults.cadenzas.active must be a list")
    if not any(
        isinstance(item, dict)
        and item.get("directory") == "{{workspace}}/shared/active"
        for item in active_cadenzas
    ):
        active_cadenzas.append(
            {
                "directory": "{{workspace}}/shared/active",
                "as": "context",
                "phases": ["all"],
                "required": True,
            }
        )
    shape_config["techniques_dir"] = str(techniques_dir.resolve())
    shape_config["agents"] = [copy.deepcopy(agent_def)]

    output = scratch / "scores"
    pipeline = CompilationPipeline(
        agents_dir=scratch / "agents",
        techniques_dir=techniques_dir,
    )
    pipeline.compile_config(shape_config, output, base_dir=scratch)
    score_path = output / f"{shape}-{agent_def['name']}.yaml"
    score = yaml.safe_load(score_path.read_text())
    if not isinstance(score, dict):
        raise ValueError(f"Compiler produced invalid score: {score_path}")
    return score


def _portable_seed(agent_def: dict[str, Any]) -> dict[str, Any]:
    seed = {
        key: copy.deepcopy(agent_def[key])
        for key in _SEED_KEYS
        if key in agent_def
    }
    seed.setdefault("seed_version", "1.0.0")
    return seed


def _replace_strings(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        replaced = value
        for source, target in replacements.items():
            replaced = replaced.replace(source, target)
        return replaced
    if isinstance(value, list):
        return [_replace_strings(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_strings(item, replacements)
            for key, item in value.items()
        }
    return value


def _localize_score(value: Any, replacements: dict[str, str]) -> Any:
    """Relocate score paths while preserving shell-command argument boundaries."""
    if isinstance(value, list):
        return [_localize_score(item, replacements) for item in value]
    if isinstance(value, dict):
        localized: dict[Any, Any] = {}
        for key, item in value.items():
            if key == "command" and isinstance(item, str):
                command = item
                for source, target in replacements.items():
                    command = command.replace(source, shlex.quote(target))
                localized[key] = command
            else:
                localized[key] = _localize_score(item, replacements)
        return localized
    return _replace_strings(value, replacements)


def _write_yaml(path: Path, value: Any) -> None:
    _atomic_write_bytes(path, _yaml_bytes(value))


def _yaml_bytes(value: Any) -> bytes:
    return yaml.safe_dump(
        value,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=120,
    ).encode()


def _write_personal_cadenza_seed(output_dir: Path, agent_name: str) -> list[Path]:
    """Copy the canonical four-file active cadenza as portable agent data."""
    source_root = files("marianne_compiler").joinpath("assets/shared-seed/shared/active")
    target_root = output_dir / "seeds" / agent_name / "cadenzas" / "personal" / "active"
    written: list[Path] = []
    for source in sorted(source_root.iterdir(), key=lambda item: item.name):
        if not source.is_file():
            continue
        target = target_root / source.name
        _atomic_write_bytes(target, source.read_bytes())
        written.append(target)
    return written


def _sync_managed_assets(
    sources: dict[str, AssetSource],
    *,
    target_root: Path,
    baseline_path: Path,
    conflict_path: Path,
    dry_run: bool,
) -> dict[str, list[dict[str, str]]]:
    """Update untouched package assets while preserving every local divergence."""
    _assert_managed_target(target_root, baseline_path)
    _assert_managed_target(target_root, conflict_path)
    baseline_doc = (
        yaml.safe_load(baseline_path.read_text())
        if baseline_path.is_file()
        else {}
    ) or {}
    old_hashes = baseline_doc.get("assets", {})
    if not isinstance(old_hashes, dict):
        raise ValueError(f"Invalid package asset baseline: {baseline_path}")
    for relative in [*old_hashes, *sources]:
        _validate_relative_asset_path(str(relative))
    new_hashes = {str(key): str(value) for key, value in old_hashes.items()}
    actions: list[dict[str, str]] = []
    conflicts: list[dict[str, str]] = []

    for relative, source in sorted(sources.items()):
        target = target_root / relative
        _assert_managed_target(target_root, target)
        package_hash = _hash_source(source)
        current_hash = _hash_path(target) if target.is_file() else None
        baseline_hash = old_hashes.get(relative)
        if current_hash is None:
            action = "would_create" if dry_run else "created"
            if not dry_run:
                _atomic_write_bytes(target, _asset_bytes(source))
                new_hashes[relative] = package_hash
            actions.append({"path": relative, "action": action})
        elif current_hash == package_hash:
            if not dry_run:
                new_hashes[relative] = package_hash
            actions.append({"path": relative, "action": "unchanged"})
        elif baseline_hash is not None and current_hash == baseline_hash:
            action = "would_update" if dry_run else "updated"
            if not dry_run:
                _atomic_write_bytes(target, _asset_bytes(source))
                new_hashes[relative] = package_hash
            actions.append({"path": relative, "action": action})
        else:
            conflicts.append(
                {
                    "path": relative,
                    "reason": "locally_modified_managed_asset",
                    "installed_hash": current_hash,
                    "package_hash": package_hash,
                }
            )

    for relative in sorted(set(old_hashes) - set(sources)):
        target = target_root / relative
        _assert_managed_target(target_root, target)
        current_hash = _hash_path(target) if target.is_file() else None
        baseline_hash = old_hashes[relative]
        if current_hash is None:
            new_hashes.pop(relative, None)
            actions.append({"path": relative, "action": "already_absent"})
        elif current_hash == baseline_hash:
            action = "would_remove" if dry_run else "removed"
            if not dry_run:
                target.unlink()
                new_hashes.pop(relative, None)
            actions.append({"path": relative, "action": action})
        else:
            conflicts.append(
                {
                    "path": relative,
                    "reason": "package_removed_locally_modified_asset",
                    "installed_hash": current_hash,
                    "package_hash": "removed",
                }
            )

    if not dry_run:
        _write_yaml(
            baseline_path,
            {
                "schema_version": 1,
                "kind": "marianne-agent-package-asset-baseline",
                "assets": dict(sorted(new_hashes.items())),
            },
        )
        _write_yaml(
            conflict_path,
            {
                "schema_version": 1,
                "kind": "marianne-agent-package-asset-conflicts",
                "conflicts": conflicts,
            },
        )
    return {"actions": actions, "conflicts": conflicts}


def _validate_relative_asset_path(value: str) -> None:
    path = Path(value)
    if path.is_absolute() or not value or ".." in path.parts:
        raise ValueError(f"Invalid managed asset path: {value!r}")


def _assert_managed_target(target_root: Path, target: Path) -> None:
    """Reject managed writes through any symlink below the resolved root."""
    if target_root.is_symlink():
        raise ValueError(f"Managed asset root must not be a symlink: {target_root}")
    root = target_root.resolve()
    try:
        relative = target.relative_to(target_root)
    except ValueError as exc:
        raise ValueError(f"Managed asset escapes managed root: {target}") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Managed asset path contains a symlink: {current}")
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Managed asset escapes managed root: {target}") from exc


def _verify_roster_asset_hashes(
    package_dir: Path,
    roster_agent: dict[str, Any],
    *,
    agent_name: str,
) -> None:
    raw_hashes = roster_agent.get("asset_hashes")
    if not isinstance(raw_hashes, dict) or not raw_hashes:
        raise ValueError(f"Roster asset hashes are missing for {agent_name}")
    expected_paths = {
        Path("seeds") / agent_name / "seed.yaml",
        *(
            path.relative_to(package_dir)
            for root in (
                package_dir / "seeds" / agent_name / "cadenzas",
                package_dir / "scores" / agent_name,
            )
            if root.is_dir()
            for path in root.rglob("*")
            if path.is_file()
        ),
    }
    declared_paths = {Path(str(value)) for value in raw_hashes}
    if declared_paths != expected_paths:
        raise ValueError(f"Roster asset set mismatch for {agent_name}")
    for relative, expected_hash in raw_hashes.items():
        _validate_relative_asset_path(str(relative))
        path = package_dir / str(relative)
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Packaged asset is missing or symlinked: {path}")
        if _hash_path(path) != expected_hash:
            raise ValueError(f"Packaged asset hash mismatch: {relative}")


def _read_preserved_package_readme(output_dir: Path) -> bytes | None:
    if not output_dir.exists():
        return None
    if not output_dir.is_dir() or output_dir.is_symlink():
        raise ValueError(f"Package output must be a real directory: {output_dir}")
    unknown = {
        path.name
        for path in output_dir.iterdir()
        if path.name not in {"README.md", "roster.yaml", "scores", "seeds"}
    }
    if unknown:
        raise ValueError(
            "Package output contains unmanaged top-level entries: "
            + ", ".join(sorted(unknown))
        )
    readme = output_dir / "README.md"
    if not readme.exists():
        return None
    if readme.is_symlink() or not readme.is_file():
        raise ValueError(f"Package README must be a regular file: {readme}")
    return readme.read_bytes()


def _publish_package_directory(staged: Path, output: Path) -> None:
    """Publish a fully built directory and roll back any failed exchange."""
    if not output.exists():
        os.replace(staged, output)
        return
    backup = Path(tempfile.mkdtemp(prefix=f".{output.name}.previous-", dir=output.parent))
    backup.rmdir()
    os.replace(output, backup)
    try:
        os.replace(staged, output)
    except BaseException:
        os.replace(backup, output)
        raise
    shutil.rmtree(backup)


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    """Replace one managed asset atomically so interruption cannot truncate it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(raw_temp)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _hash_path(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _asset_bytes(source: AssetSource) -> bytes:
    return source if isinstance(source, bytes) else source.read_bytes()


def _hash_source(source: AssetSource) -> str:
    return f"sha256:{hashlib.sha256(_asset_bytes(source)).hexdigest()}"


__all__ = ["SCORE_SHAPES", "generate_agent_package", "install_agent_package"]
