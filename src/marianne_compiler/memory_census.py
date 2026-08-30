"""Read-only census for canonical and copied Marianne agent memory trees."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

IDENTITY_LAYERS = ("identity.md", "profile.yaml", "recent.md", "growth.md")
SNAPSHOT_MARKERS = frozenset({"SCORES", "WORSKPACES", "WORKSPACES", "workspaces"})


def census_agent_memory(
    *,
    canonical_root: Path,
    search_roots: Iterable[Path],
) -> dict[str, Any]:
    """Classify agent identity trees without writing or importing anything.

    The canonical root is authoritative. Complete copies below score/workspace
    artifact trees are snapshots; partial or unclassified trees are unknown and
    require human review. Symlinked roots resolving to the canonical root are
    aliases, not duplicate memory authorities.
    """
    canonical_root = canonical_root.expanduser()
    canonical_real = canonical_root.resolve()
    canonical_entries = _immediate_agent_entries(canonical_real)
    canonical_by_id = {entry["agent_id"]: entry for entry in canonical_entries}

    aliases: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    observed_real_paths = {Path(entry["path"]) for entry in canonical_entries}

    for raw_root in search_roots:
        root = raw_root.expanduser()
        if not root.exists():
            continue
        resolved_root = root.resolve()
        if resolved_root == canonical_real:
            if root.absolute() != canonical_root.absolute():
                aliases.append(
                    {
                        "path": str(resolved_root),
                        "source_path": str(root.absolute()),
                        "kind": "canonical_root_alias",
                    }
                )
            continue

        for candidate in _identity_candidates(root):
            real_candidate = candidate.resolve()
            if real_candidate in observed_real_paths:
                continue
            observed_real_paths.add(real_candidate)
            entry = _entry_for(candidate)
            canonical = canonical_by_id.get(entry["agent_id"])
            if canonical:
                entry["relationship"] = (
                    "exact_canonical_copy"
                    if entry.get("fingerprint") == canonical.get("fingerprint")
                    else "divergent_from_canonical"
                )
            else:
                entry["relationship"] = "no_canonical_agent"

            if not entry["missing_layers"] and _looks_like_snapshot(candidate):
                entry["kind"] = "workspace_snapshot"
                snapshots.append(entry)
            else:
                entry["kind"] = "unknown_identity_tree"
                unknown.append(entry)

    return {
        "schema_version": 1,
        "mode": "read_only",
        "canonical_root": str(canonical_real),
        "canonical": sorted(canonical_entries, key=_entry_sort_key),
        "aliases": sorted(aliases, key=lambda item: item["source_path"]),
        "snapshots": sorted(snapshots, key=_entry_sort_key),
        "unknown": sorted(unknown, key=_entry_sort_key),
    }


def _identity_candidates(root: Path) -> list[Path]:
    candidates: set[Path] = set()
    for filename in IDENTITY_LAYERS:
        for path in root.rglob(filename):
            if path.is_file():
                candidates.add(path.parent)
    return sorted(candidates, key=lambda path: str(path.absolute()))


def _immediate_agent_entries(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for candidate in sorted(root.iterdir(), key=lambda path: path.name):
        if not candidate.is_dir():
            continue
        if not any((candidate / filename).is_file() for filename in IDENTITY_LAYERS):
            continue
        entry = _entry_for(candidate)
        entry["kind"] = "canonical"
        entry["relationship"] = "authority"
        entries.append(entry)
    return entries


def _entry_for(path: Path) -> dict[str, Any]:
    present = [filename for filename in IDENTITY_LAYERS if (path / filename).is_file()]
    missing = sorted(set(IDENTITY_LAYERS) - set(present))
    agent_id = _agent_id(path)
    entry: dict[str, Any] = {
        "agent_id": agent_id,
        "path": str(path.resolve()),
        "source_path": str(path.absolute()),
        "present_layers": present,
        "missing_layers": missing,
    }
    if not missing:
        entry["fingerprint"] = _fingerprint(path)
    return entry


def _agent_id(path: Path) -> str:
    profile_path = path / "profile.yaml"
    if profile_path.is_file():
        try:
            profile = yaml.safe_load(profile_path.read_text()) or {}
        except yaml.YAMLError:
            profile = {}
        if isinstance(profile, dict) and profile.get("name"):
            return str(profile["name"]).strip().lower()
    return path.name.strip().lower()


def _fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    for filename in IDENTITY_LAYERS:
        digest.update(filename.encode())
        digest.update(b"\0")
        digest.update((path / filename).read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _looks_like_snapshot(path: Path) -> bool:
    return bool(set(path.parts) & SNAPSHOT_MARKERS)


def _entry_sort_key(item: dict[str, Any]) -> tuple[str, str]:
    return (str(item.get("agent_id", "")), str(item.get("source_path", "")))


__all__ = ["IDENTITY_LAYERS", "census_agent_memory"]
