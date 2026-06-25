"""Workspace seed artifacts for compiled Marianne fleets."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Any


class WorkspaceSeeder:
    """Create shared fleet workspace directories and starter artifacts.

    The seeder is intentionally conservative: it creates missing directories
    and files, but never overwrites existing coordination state.
    """

    def seed(self, workspace: str | Path, config: dict[str, Any]) -> list[Path]:
        """Seed a workspace when requested by compiler config.

        Args:
            workspace: Workspace directory path.
            config: Parsed compiler config dict.

        Returns:
            Paths written during this invocation.
        """
        if not self._enabled(config):
            return []

        workspace_path = Path(workspace).expanduser()
        workspace_path.mkdir(parents=True, exist_ok=True)

        for relative in self._directories():
            (workspace_path / relative).mkdir(parents=True, exist_ok=True)

        written: list[Path] = []
        seed_root = files("marianne_compiler").joinpath("assets/shared-seed")
        for item in self._walk_seed_files(seed_root):
            relative = Path(*item.relative_to(seed_root).parts)
            target = workspace_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                continue
            target.write_text(item.read_text())
            written.append(target)

        return written

    @staticmethod
    def _walk_seed_files(root: Any) -> list[Any]:
        files_out: list[Any] = []
        for item in root.iterdir():
            if item.is_file():
                files_out.append(item)
            elif item.is_dir():
                files_out.extend(WorkspaceSeeder._walk_seed_files(item))
        return files_out

    @staticmethod
    def _enabled(config: dict[str, Any]) -> bool:
        defaults = config.get("defaults", {})
        shared = {}
        if isinstance(defaults, dict):
            shared = defaults.get("shared_workspace", {})
        if not isinstance(shared, dict):
            return False
        return bool(shared.get("enabled", False) and shared.get("seed", True))

    @staticmethod
    def _directories() -> tuple[Path, ...]:
        return (
            Path("shared/active"),
            Path("shared/archive"),
            Path("shared/decisions"),
            Path("shared/directives"),
            Path("shared/findings"),
            Path("shared/plans"),
            Path("shared/specs"),
            Path("shared/techniques"),
            Path("agents"),
            Path("collective"),
            Path("playspace"),
            Path("cycle-state"),
        )
