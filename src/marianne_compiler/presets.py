"""Built-in compiler presets shipped with Marianne."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

BUILTIN_PRESETS: dict[str, str] = {
    "generic-fleet": "assets/generic-fleet.yaml",
}


def list_builtin_presets() -> list[str]:
    """Return available built-in preset names."""
    return sorted(BUILTIN_PRESETS)


def load_builtin_preset(name: str) -> dict[str, Any]:
    """Load a built-in compiler preset config."""
    resource_name = BUILTIN_PRESETS.get(name)
    if not resource_name:
        available = ", ".join(list_builtin_presets())
        raise ValueError(f"Unknown compiler preset '{name}'. Available presets: {available}")

    resource = files("marianne_compiler").joinpath(resource_name)
    return yaml.safe_load(resource.read_text()) or {}


def prepare_builtin_preset(
    config: dict[str, Any],
    *,
    name: str,
    cwd: Path,
    workspace: Path | None = None,
) -> dict[str, Any]:
    """Apply invocation-local defaults to a built-in preset config."""
    prepared = dict(config)
    project = dict(prepared.get("project", {}))
    resolved_workspace = workspace or cwd / ".marianne" / "workspaces" / name
    project["workspace"] = str(resolved_workspace.expanduser().resolve())
    prepared["project"] = project

    if not prepared.get("techniques_dir"):
        techniques_dir = _discover_plugin_techniques(cwd)
        if techniques_dir:
            prepared["techniques_dir"] = str(techniques_dir)

    return prepared


def _discover_plugin_techniques(cwd: Path) -> Path | None:
    """Find the default Marianne technique document directory."""
    packaged = Path(__file__).resolve().parent / "assets" / "techniques"
    candidates = [
        cwd / "plugins" / "marianne" / "techniques",
        packaged,
        Path(__file__).resolve().parents[3] / "plugins" / "marianne" / "techniques",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    return None


__all__ = [
    "BUILTIN_PRESETS",
    "list_builtin_presets",
    "load_builtin_preset",
    "prepare_builtin_preset",
]
