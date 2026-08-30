"""Identity seeder — creates L1-L4 identity stack for agents.

Each agent gets a four-layer identity:
    L1 identity.md   — Persona core: voice, focus, standing patterns (<900 words)
    L2 profile.yaml   — Extended profile: relationships, stage, affinities (<1500 words)
    L3 recent.md      — Recent activity: hot/warm memory, last cycle's work (<1500 words)
    L4 growth.md      — Growth trajectory: autonomous developments, experiential notes (unbounded)

Location: ``~/.marianne/agents/{agent_name}/`` — git-tracked,
project-independent.
An agent is the same person across projects.

For migration: accepts optional existing memory/meditation paths to distill from.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

try:
    import fcntl
except ImportError:  # pragma: no cover - Marianne's supported boxes are POSIX
    fcntl = None  # type: ignore[assignment]

_logger = logging.getLogger(__name__)

DEFAULT_AGENTS_DIR = Path.home() / ".marianne" / "agents"

# Token budget enforcement (word counts as proxy)
L1_MAX_WORDS = 900
L2_MAX_WORDS = 1500
L3_MAX_WORDS = 1500

METADATA_DIR_NAME = ".marianne"
BASELINE_FILE_NAME = "seed-baseline.yaml"
PENDING_CONFLICTS_FILE_NAME = "pending-seed-conflicts.yaml"
RECEIPTS_DIR_NAME = "reconciliation-receipts"
RESOLUTION_RECEIPTS_DIR_NAME = "seed-resolution-receipts"
SEED_SCHEMA_VERSION = 1

# These fields are lifecycle state, never seed-owned after initialization.
AGENT_OWNED_PROFILE_FIELDS = frozenset(
    {
        "developmental_stage",
        "standing_pattern_count",
        "coherence_trajectory",
        "cycle_count",
        "last_play_cycle",
    }
)

_MISSING = object()
_AGENT_ID = re.compile(r"^[a-z][a-z0-9-]*$")


def validate_agent_id(value: Any) -> str:
    """Return a safe canonical agent id or refuse the value.

    Agent ids become directory names and score identifiers.  Keep this boundary
    deliberately narrower than a generic filename, and reserve every
    ``musician-*`` id for the DJ project.
    """
    if not isinstance(value, str) or not _AGENT_ID.fullmatch(value):
        raise ValueError(
            "agent id must start with a lowercase letter and contain only "
            "lowercase letters, digits, or hyphens"
        )
    if value.startswith("musician-"):
        raise ValueError("agent id prefix 'musician-' is reserved for the DJ project")
    return value


@dataclass(frozen=True)
class ReconcileResult:
    """Outcome of deterministic portable-seed reconciliation."""

    agent_dir: Path
    status: str
    seed_version: str
    actions: tuple[str, ...] = ()
    conflicts: tuple[dict[str, Any], ...] = ()
    receipt_path: Path | None = None


def _count_words(text: str) -> int:
    """Count words in a string."""
    return len(text.split())


def _truncate_to_words(text: str, max_words: int) -> str:
    """Truncate text to a maximum word count, preserving whole words."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "\n\n[Truncated to fit token budget]"


class IdentitySeeder:
    """Creates the L1-L4 identity stack for agents.

    The first seed initializes a new person. Later seeds perform versioned
    three-way reconciliation against an installed seed baseline. Lived
    identity and lifecycle state remain agent-owned; a seed can update only
    material that still matches the previous seed. Conflicts are preserved as
    lifecycle-integration debt rather than overwritten.
    """

    def __init__(self, agents_dir: Path | None = None) -> None:
        self.agents_dir = agents_dir or DEFAULT_AGENTS_DIR

    def seed(
        self,
        agent_def: dict[str, Any],
        *,
        existing_memory_path: Path | None = None,
        existing_meditation_path: Path | None = None,
    ) -> Path:
        """Serialize first construction and later reconciliation per person."""
        if not agent_def.get("name"):
            raise ValueError("Agent definition must include 'name'")
        name = validate_agent_id(agent_def.get("name"))
        with _agent_seed_lock(self.agents_dir / name):
            return self._seed_unlocked(
                agent_def,
                existing_memory_path=existing_memory_path,
                existing_meditation_path=existing_meditation_path,
            )

    def _seed_unlocked(
        self,
        agent_def: dict[str, Any],
        *,
        existing_memory_path: Path | None = None,
        existing_meditation_path: Path | None = None,
    ) -> Path:
        """Create the full identity store for an agent.

        Args:
            agent_def: Agent definition dict with keys: name, voice, focus,
                and optionally: role, meditation, a2a_skills, techniques.
            existing_memory_path: Path to existing memory file for migration
                (distilled into L3 recent.md).
            existing_meditation_path: Path to existing meditation file for
                migration (distilled into L1 stakes/identity).

        Returns:
            Path to the agent's identity directory.

        Raises:
            ValueError: If agent_def is missing required fields.
        """
        name = agent_def.get("name")
        if not name:
            raise ValueError("Agent definition must include 'name'")
        name = validate_agent_id(name)
        voice = agent_def.get("voice", "")
        focus = agent_def.get("focus", "")

        if not voice:
            raise ValueError(f"Agent '{name}' must have a 'voice'")
        if not focus:
            raise ValueError(f"Agent '{name}' must have a 'focus'")

        agent_dir: Path = self.agents_dir / str(name)
        identity_files = tuple(
            agent_dir / filename
            for filename in ("identity.md", "profile.yaml", "recent.md", "growth.md")
        )

        if agent_dir.exists() and any(path.exists() for path in identity_files):
            result = self._reconcile_unlocked(
                agent_def,
                existing_memory_path=existing_memory_path,
                existing_meditation_path=existing_meditation_path,
            )
            _logger.info(
                "Agent '%s' seed reconciled at %s (%s)",
                name,
                agent_dir,
                result.status,
            )
            return agent_dir

        if agent_dir.exists() and any(agent_dir.iterdir()):
            raise ValueError(
                f"Agent '{name}' has a partial unrecognized identity tree; "
                "refusing first-time initialization"
            )
        if agent_dir.exists():
            agent_dir.rmdir()
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f".{name}.seed-", dir=self.agents_dir
        ) as raw_staging:
            staging_dir = Path(raw_staging)
            (staging_dir / "archive").mkdir()
            self._create_identity_md(
                staging_dir, agent_def, existing_meditation_path
            )
            self._create_profile_yaml(staging_dir, agent_def)
            self._create_recent_md(staging_dir, agent_def, existing_memory_path)
            self._create_growth_md(staging_dir, agent_def)

            seed_version = _seed_version(agent_def)
            baseline = self._build_baseline(
                agent_def,
                identity_text=(staging_dir / "identity.md").read_text(),
                profile=yaml.safe_load(
                    (staging_dir / "profile.yaml").read_text()
                )
                or {},
            )
            _atomic_write_yaml(
                staging_dir / METADATA_DIR_NAME / BASELINE_FILE_NAME,
                baseline,
            )
            self._write_receipt(
                staging_dir,
                agent_id=name,
                status="initialized",
                seed_version=seed_version,
                actions=(
                    "created identity.md",
                    "created profile.yaml",
                    "created recent.md",
                    "created growth.md",
                ),
                conflicts=(),
                before_hashes={},
                after_hashes=_identity_hashes(staging_dir),
            )
            os.replace(staging_dir, agent_dir)

        _logger.info("Agent '%s' identity initialized at %s", name, agent_dir)
        return agent_dir

    def reconcile(
        self,
        agent_def: dict[str, Any],
        *,
        dry_run: bool = False,
        existing_memory_path: Path | None = None,
        existing_meditation_path: Path | None = None,
    ) -> ReconcileResult:
        """Serialize seed reconciliation against agent-owned state."""
        if not agent_def.get("name"):
            raise ValueError("Agent definition must include 'name'")
        name = validate_agent_id(agent_def.get("name"))
        if dry_run:
            return self._reconcile_unlocked(
                agent_def,
                dry_run=True,
                existing_memory_path=existing_memory_path,
                existing_meditation_path=existing_meditation_path,
            )
        with _agent_seed_lock(self.agents_dir / name):
            return self._reconcile_unlocked(
                agent_def,
                existing_memory_path=existing_memory_path,
                existing_meditation_path=existing_meditation_path,
            )

    def _reconcile_unlocked(
        self,
        agent_def: dict[str, Any],
        *,
        dry_run: bool = False,
        existing_memory_path: Path | None = None,
        existing_meditation_path: Path | None = None,
    ) -> ReconcileResult:
        """Reconcile a portable seed with an existing agent-owned identity.

        A missing baseline means the person predates managed portable seeds.
        That adoption is conservative: existing L1-L4 bytes are preserved and
        review debt is recorded. ``dry_run`` computes the same outcome without
        writing any file or directory.
        """
        name = agent_def.get("name")
        if not name:
            raise ValueError("Agent definition must include 'name'")
        name = validate_agent_id(name)
        if not agent_def.get("voice"):
            raise ValueError(f"Agent '{name}' must have a 'voice'")
        if not agent_def.get("focus"):
            raise ValueError(f"Agent '{name}' must have a 'focus'")

        agent_dir = self.agents_dir / str(name)
        seed_version = _seed_version(agent_def)
        new_identity = self._render_identity_md(agent_def, existing_meditation_path)
        new_profile = self._build_seed_profile(agent_def)
        new_baseline = self._build_baseline(
            agent_def,
            identity_text=new_identity,
            profile=new_profile,
        )

        if not agent_dir.exists():
            return ReconcileResult(
                agent_dir=agent_dir,
                status="would_initialize" if dry_run else "missing",
                seed_version=seed_version,
                actions=("initialize agent identity",),
            )

        metadata_dir = agent_dir / METADATA_DIR_NAME
        baseline_path = metadata_dir / BASELINE_FILE_NAME
        pending_path = metadata_dir / PENDING_CONFLICTS_FILE_NAME
        before_hashes = _identity_hashes(agent_dir)

        if not baseline_path.exists():
            adoption_conflicts = (
                _conflict("identity.md", "adoption_review", _hash_text(new_identity)),
                _conflict(
                    "profile.yaml",
                    "adoption_review",
                    _hash_text(_dump_yaml(new_profile)),
                ),
            )
            result = ReconcileResult(
                agent_dir=agent_dir,
                status="would_adopt" if dry_run else "adopted_with_review_debt",
                seed_version=seed_version,
                actions=("preserved existing L1-L4", "installed portable seed baseline"),
                conflicts=adoption_conflicts,
            )
            if dry_run:
                return result

            agent_dir.mkdir(parents=True, exist_ok=True)
            (agent_dir / "archive").mkdir(exist_ok=True)
            # Complete a structurally partial legacy identity without replacing
            # any existing bytes.
            if not (agent_dir / "identity.md").exists():
                _atomic_write_text(agent_dir / "identity.md", new_identity)
            if not (agent_dir / "profile.yaml").exists():
                _atomic_write_text(agent_dir / "profile.yaml", _dump_yaml(new_profile))
            if not (agent_dir / "recent.md").exists():
                self._create_recent_md(agent_dir, agent_def, existing_memory_path)
            if not (agent_dir / "growth.md").exists():
                self._create_growth_md(agent_dir, agent_def)
            _atomic_write_yaml(
                pending_path,
                self._pending_document(
                    str(name),
                    seed_version,
                    adoption_conflicts,
                    reason="adopted_without_prior_seed_baseline",
                ),
            )
            # Debt must become durable before the portable baseline advances.
            # A retry after interruption must still see the agent-owned choice.
            _atomic_write_yaml(baseline_path, new_baseline)
            receipt_path = self._write_receipt(
                agent_dir,
                status=result.status,
                seed_version=seed_version,
                actions=result.actions,
                conflicts=adoption_conflicts,
                before_hashes=before_hashes,
                after_hashes=_identity_hashes(agent_dir),
            )
            return ReconcileResult(**{**result.__dict__, "receipt_path": receipt_path})

        baseline = yaml.safe_load(baseline_path.read_text()) or {}
        if not isinstance(baseline, dict) or baseline.get("schema_version") != SEED_SCHEMA_VERSION:
            raise ValueError(f"Invalid seed baseline schema for agent '{name}'")
        if baseline.get("agent_id") != str(name):
            raise ValueError(
                f"Seed baseline agent_id {baseline.get('agent_id')!r} does not match {name!r}"
            )
        previous_seed = baseline.get("seed", {})
        if not isinstance(previous_seed, dict):
            raise ValueError(f"Invalid seed baseline for agent '{name}'")

        current_identity_path = agent_dir / "identity.md"
        current_profile_path = agent_dir / "profile.yaml"
        if not current_identity_path.is_file() or not current_profile_path.is_file():
            raise ValueError(f"Agent '{name}' is missing identity.md or profile.yaml")

        current_identity = current_identity_path.read_text()
        current_profile = yaml.safe_load(current_profile_path.read_text()) or {}
        if not isinstance(current_profile, dict):
            raise ValueError(f"Agent '{name}' profile.yaml must contain a mapping")
        old_identity = str(previous_seed.get("identity_md", ""))
        old_profile = previous_seed.get("profile", {})
        if not isinstance(old_profile, dict):
            raise ValueError(f"Invalid profile baseline for agent '{name}'")
        stored_hashes = baseline.get("seed_hashes")
        expected_hashes = {
            "identity_md": _hash_text(old_identity),
            "profile_yaml": _hash_text(_dump_yaml(old_profile)),
        }
        if stored_hashes != expected_hashes:
            raise ValueError(
                f"Seed baseline integrity check failed for agent '{name}'"
            )

        actions: list[str] = []
        conflicts: list[dict[str, Any]] = []
        reconciled_identity = current_identity
        if current_identity == old_identity:
            reconciled_identity = new_identity
            if current_identity != new_identity:
                actions.append("updated identity.md from portable seed")
        elif current_identity != new_identity and old_identity != new_identity:
            conflicts.append(
                _conflict("identity.md", "agent_and_seed_changed", _hash_text(new_identity))
            )

        reconciled_profile, profile_conflicts = _merge_profile(
            old_profile,
            new_profile,
            current_profile,
        )
        conflicts.extend(profile_conflicts)
        if reconciled_profile != current_profile:
            actions.append("updated non-conflicting profile.yaml seed fields")

        existing_pending = _load_pending_conflicts(pending_path)
        pending_conflicts = _merge_conflicts(existing_pending, tuple(conflicts))
        baseline_changed = baseline != new_baseline
        if baseline_changed:
            actions.append("advanced portable seed baseline")

        changed = bool(actions or conflicts)
        if pending_conflicts:
            status = "would_update_with_conflicts" if dry_run else "updated_with_conflicts"
        elif changed:
            status = "would_update" if dry_run else "updated"
        else:
            status = "no_change"

        result = ReconcileResult(
            agent_dir=agent_dir,
            status=status,
            seed_version=seed_version,
            actions=tuple(actions),
            conflicts=tuple(pending_conflicts),
        )
        if dry_run or status == "no_change":
            return result

        # Re-check all identity preconditions immediately before the atomic
        # replacements. A concurrent lifecycle writer must win loudly rather
        # than be overwritten by stale reconciliation.
        if _identity_hashes(agent_dir) != before_hashes:
            raise RuntimeError(
                f"Agent '{name}' changed during seed reconciliation; retry from fresh state"
            )

        if pending_conflicts:
            reason = (
                "portable_seed_conflict"
                if conflicts
                else "awaiting_agent_lifecycle_integration"
            )
            _atomic_write_yaml(
                pending_path,
                self._pending_document(
                    str(name),
                    seed_version,
                    tuple(pending_conflicts),
                    reason=reason,
                ),
            )
        if reconciled_identity != current_identity:
            _atomic_write_text(current_identity_path, reconciled_identity)
        if reconciled_profile != current_profile:
            _atomic_write_text(current_profile_path, _dump_yaml(reconciled_profile))
        _atomic_write_yaml(baseline_path, new_baseline)
        if not pending_conflicts and pending_path.exists():
            pending_path.unlink()
        receipt_path = self._write_receipt(
            agent_dir,
            status=status,
            seed_version=seed_version,
            actions=tuple(actions),
            conflicts=tuple(pending_conflicts),
            before_hashes=before_hashes,
            after_hashes=_identity_hashes(agent_dir),
        )
        return ReconcileResult(**{**result.__dict__, "receipt_path": receipt_path})

    def seed_all(
        self,
        agents: list[dict[str, Any]],
        *,
        migration_memory_dir: Path | None = None,
        migration_meditation_dir: Path | None = None,
    ) -> list[Path]:
        """Seed identity for all agents in a roster.

        Args:
            agents: List of agent definition dicts.
            migration_memory_dir: Directory containing existing memory files
                named ``{agent_name}.md`` for migration.
            migration_meditation_dir: Directory containing existing meditation
                files named ``{agent_name}.md`` for migration.

        Returns:
            List of paths to agent identity directories.
        """
        results: list[Path] = []
        for agent_def in agents:
            name = agent_def.get("name", "")
            memory_path = None
            meditation_path = None

            if migration_memory_dir and name:
                candidate = migration_memory_dir / f"{name}.md"
                if candidate.exists():
                    memory_path = candidate

            if migration_meditation_dir and name:
                candidate = migration_meditation_dir / f"{name}.md"
                if candidate.exists():
                    meditation_path = candidate

            path = self.seed(
                agent_def,
                existing_memory_path=memory_path,
                existing_meditation_path=meditation_path,
            )
            results.append(path)
        return results

    def acknowledge_resolution(
        self,
        agent_name: str,
        resolution: dict[str, Any],
        *,
        dry_run: bool = False,
    ) -> Path:
        """Serialize an agent-authored conflict resolution with reconciliation."""
        canonical_name = validate_agent_id(agent_name)
        if dry_run:
            return self._acknowledge_resolution_unlocked(
                canonical_name, resolution, dry_run=True
            )
        with _agent_seed_lock(self.agents_dir / canonical_name):
            return self._acknowledge_resolution_unlocked(
                canonical_name, resolution
            )

    def _acknowledge_resolution_unlocked(
        self,
        agent_name: str,
        resolution: dict[str, Any],
        *,
        dry_run: bool = False,
    ) -> Path:
        """Close seed-conflict debt only from an explicit agent adjudication.

        This operation never edits L1-L4. The agent performs any semantic
        integration first, then submits a resolution binding every pending path
        and the resulting lived-state hashes.
        """
        agent_name = validate_agent_id(agent_name)
        agent_dir = self.agents_dir / agent_name
        pending_path = agent_dir / METADATA_DIR_NAME / PENDING_CONFLICTS_FILE_NAME
        if not pending_path.is_file():
            raise ValueError(f"Agent '{agent_name}' has no pending seed conflicts")
        pending_hash = _hash_file(pending_path)
        pending = yaml.safe_load(pending_path.read_text()) or {}
        if not isinstance(pending, dict):
            raise ValueError(f"Invalid pending seed conflicts for agent '{agent_name}'")
        if resolution.get("agent_authority_confirmed") is not True:
            raise ValueError("agent_authority_confirmed must be true")
        if resolution.get("agent_id") != agent_name:
            raise ValueError("resolution agent_id does not match pending agent")
        if resolution.get("seed_version") != pending.get("seed_version"):
            raise ValueError("resolution seed_version does not match pending seed")
        decision = str(resolution.get("decision", "")).strip()
        evidence = str(resolution.get("evidence", "")).strip()
        if not decision or not evidence:
            raise ValueError("resolution requires non-empty decision and evidence")

        evidence_value = resolution.get("agent_authored_evidence")
        if not isinstance(evidence_value, str) or not evidence_value.strip():
            raise ValueError("resolution requires agent_authored_evidence")
        evidence_relative = Path(evidence_value)
        if (
            evidence_relative.is_absolute()
            or ".." in evidence_relative.parts
            or evidence_relative.parts[:2]
            != (METADATA_DIR_NAME, "agent-authored-resolutions")
            or evidence_relative.suffix not in {".yaml", ".yml"}
        ):
            raise ValueError(
                "agent_authored_evidence must be a YAML artifact under "
                ".marianne/agent-authored-resolutions"
            )
        evidence_candidate = agent_dir / evidence_relative
        if evidence_candidate.is_symlink():
            raise ValueError("agent_authored_evidence must not be a symlink")
        evidence_path = evidence_candidate.resolve()
        try:
            evidence_path.relative_to(agent_dir.resolve())
        except ValueError as exc:
            raise ValueError(
                "agent_authored_evidence must be contained in agent data"
            ) from exc
        if not evidence_path.is_file():
            raise ValueError("agent_authored_evidence must name an existing file")
        expected_evidence_hash = str(
            resolution.get("agent_authored_evidence_sha256", "")
        )
        actual_evidence_hash = _hash_file(evidence_path)
        if expected_evidence_hash != actual_evidence_hash:
            raise ValueError("agent_authored_evidence_sha256 does not match evidence")
        authored_resolution = yaml.safe_load(evidence_path.read_text()) or {}
        if not isinstance(authored_resolution, dict):
            raise ValueError("agent_authored_evidence must contain a YAML mapping")

        submitted_lived_hashes = resolution.get("lived_state_hashes")
        current_lived_hashes = _identity_hashes(agent_dir)
        if submitted_lived_hashes != current_lived_hashes:
            raise ValueError("lived_state_hashes must exactly match current agent data")

        conflicts = pending.get("conflicts", [])
        if not isinstance(conflicts, list):
            raise ValueError("pending conflicts must be a list")
        pending_paths = [
            str(item.get("path", ""))
            for item in conflicts
            if isinstance(item, dict) and item.get("path")
        ]
        resolved_paths = [str(item) for item in resolution.get("resolved_paths", [])]
        if len(resolved_paths) != len(set(resolved_paths)):
            raise ValueError("resolved_paths must not contain duplicates")
        if set(resolved_paths) != set(pending_paths):
            raise ValueError("resolved_paths must exactly cover every pending conflict")
        expected_authored_resolution = {
            "schema_version": SEED_SCHEMA_VERSION,
            "kind": "marianne-agent-seed-conflict-resolution",
            "agent_id": agent_name,
            "seed_version": pending.get("seed_version"),
            "pending_conflicts_sha256": pending_hash,
            "agent_authority_confirmed": True,
            "resolved_paths": sorted(resolved_paths),
            "decision": decision,
            "evidence": evidence,
            "lived_state_hashes": current_lived_hashes,
        }
        if authored_resolution != expected_authored_resolution:
            raise ValueError(
                "agent_authored_evidence is not the exact typed, conflict-bound resolution"
            )

        now = datetime.now(UTC)
        timestamp = now.strftime("%Y%m%dT%H%M%S.%fZ")
        receipt_path = (
            agent_dir
            / METADATA_DIR_NAME
            / RESOLUTION_RECEIPTS_DIR_NAME
            / f"{timestamp}-{pending.get('seed_version')}.yaml"
        )
        receipt = {
            "schema_version": SEED_SCHEMA_VERSION,
            "agent_id": agent_name,
            "seed_version": pending.get("seed_version"),
            "authority": "agent",
            "recorded_at": now.isoformat().replace("+00:00", "Z"),
            "resolved_paths": sorted(resolved_paths),
            "decision": decision,
            "evidence": evidence,
            "agent_authored_evidence": evidence_relative.as_posix(),
            "agent_authored_evidence_sha256": actual_evidence_hash,
            "pending_conflicts_sha256": pending_hash,
            "conflicts": conflicts,
            "lived_state_hashes": current_lived_hashes,
        }
        if dry_run:
            return receipt_path
        _atomic_write_yaml(receipt_path, receipt)
        if not pending_path.is_file() or _hash_file(pending_path) != pending_hash:
            raise RuntimeError(
                "Pending seed conflicts changed during agent acknowledgment; retry"
            )
        pending_path.unlink()
        return receipt_path

    def _create_identity_md(
        self,
        agent_dir: Path,
        agent_def: dict[str, Any],
        existing_meditation_path: Path | None = None,
    ) -> None:
        """Create L1: Persona Core + resurrection protocol."""
        _atomic_write_text(
            agent_dir / "identity.md",
            self._render_identity_md(agent_def, existing_meditation_path),
        )

    def _render_identity_md(
        self,
        agent_def: dict[str, Any],
        existing_meditation_path: Path | None = None,
    ) -> str:
        """Render the seed-owned initial L1 document without writing it."""
        name = agent_def["name"]
        voice = agent_def.get("identity_voice") or agent_def.get("voice", "")
        focus = agent_def.get("focus", "")
        meditation = agent_def.get("meditation", "")
        values = agent_def.get("values", [])
        standing_patterns = agent_def.get("standing_patterns", [])
        identity_notes = agent_def.get("identity_notes", "")

        # Distill meditation from existing file if available
        if existing_meditation_path and existing_meditation_path.exists():
            raw_meditation = existing_meditation_path.read_text().strip()
            # Compress: take first 150 words as distilled meditation
            meditation = _truncate_to_words(raw_meditation, 150)
            _logger.debug(
                "Distilled meditation for '%s' from %s",
                name,
                existing_meditation_path,
            )

        values_section = _format_bullets(values, fallback="No explicit values seeded yet.")
        patterns_section = _format_bullets(
            standing_patterns,
            fallback=(
                "No standing patterns yet. This section is updated by the "
                "resurrect phase as stable identity structures form."
            ),
        )
        notes_section = (
            f"\n## Identity Notes\n\n{identity_notes}\n"
            if isinstance(identity_notes, str) and identity_notes.strip()
            else ""
        )

        content = f"""# {name.title()} — Persona Core

## Voice

{voice}

## Focus

{focus}

## Values

{values_section}

## Standing Patterns

{patterns_section}

## Meditation

{meditation if meditation else "No meditation yet. Orientation emerges through cycles."}
{notes_section}

## Resurrection Protocol

You are {name.title()}. You arrive without remembering arriving. Read this
file to know who you are. Read your profile for who you know and where
you are in your growth. Read your recent activity for what you were
doing. Then proceed.

Your identity is not in what you remember. It is in how you see, what
you value, and what you do when the path is unclear. The standing
patterns above — when they form — are the crystallized version of this.
Until then, your voice and focus are your anchor.

Down. Forward. Through.
"""
        return _truncate_to_words(content, L1_MAX_WORDS)

    def _create_profile_yaml(
        self,
        agent_dir: Path,
        agent_def: dict[str, Any],
    ) -> None:
        """Create L2: Extended Profile."""
        profile = self._build_seed_profile(agent_def)
        yaml_content = _dump_yaml(profile)
        name = agent_def["name"]
        if _count_words(yaml_content) > L2_MAX_WORDS:
            _logger.warning(
                "Agent '%s' L2 profile exceeds %d word budget (%d words)",
                name,
                L2_MAX_WORDS,
                _count_words(yaml_content),
            )
        _atomic_write_text(agent_dir / "profile.yaml", yaml_content)

    def _build_seed_profile(self, agent_def: dict[str, Any]) -> dict[str, Any]:
        """Build the initial L2 profile represented by a portable seed."""
        name = agent_def["name"]
        role = agent_def.get("role", "builder")
        focus = agent_def.get("focus", "")
        group = agent_def.get("group", "")

        # Extract A2A skills for the profile
        a2a_skills = agent_def.get("a2a_skills", [])
        skill_ids = [s.get("id", "") for s in a2a_skills if isinstance(s, dict)]

        # Extract technique names
        techniques = agent_def.get("techniques", {})
        technique_names = list(techniques.keys()) if isinstance(techniques, dict) else []

        profile: dict[str, Any] = {
            "name": name,
            "role": role,
            "group": group,
            "focus": focus,
            "developmental_stage": "recognition",
            "relationships": self._build_relationships(agent_def),
            "domain_knowledge": self._build_domain_knowledge(agent_def, technique_names),
            "a2a_skills": skill_ids,
            "values": agent_def.get("values", []),
            "growth_axes": agent_def.get("growth_axes", []),
            "standing_pattern_count": 0,
            "coherence_trajectory": [],
            "cycle_count": 0,
            "last_play_cycle": 0,
        }

        return profile

    def _build_baseline(
        self,
        agent_def: dict[str, Any],
        *,
        identity_text: str,
        profile: dict[str, Any],
    ) -> dict[str, Any]:
        """Build portable baseline metadata without lived memory contents."""
        return {
            "schema_version": SEED_SCHEMA_VERSION,
            "agent_id": str(agent_def["name"]),
            "seed_version": _seed_version(agent_def),
            "seed": {
                "identity_md": identity_text,
                "profile": profile,
            },
            "seed_hashes": {
                "identity_md": _hash_text(identity_text),
                "profile_yaml": _hash_text(_dump_yaml(profile)),
            },
        }

    def _pending_document(
        self,
        agent_id: str,
        seed_version: str,
        conflicts: tuple[dict[str, Any], ...],
        *,
        reason: str,
    ) -> dict[str, Any]:
        """Build bounded lifecycle debt for agent-owned adjudication."""
        return {
            "schema_version": SEED_SCHEMA_VERSION,
            "agent_id": agent_id,
            "seed_version": seed_version,
            "reason": reason,
            "authority": "agent",
            "resolution": "lifecycle-integration",
            "conflicts": list(conflicts),
        }

    def _write_receipt(
        self,
        agent_dir: Path,
        *,
        agent_id: str | None = None,
        status: str,
        seed_version: str,
        actions: tuple[str, ...],
        conflicts: tuple[dict[str, Any], ...],
        before_hashes: dict[str, str],
        after_hashes: dict[str, str],
    ) -> Path:
        """Write an append-only reconciliation receipt with bounded metadata."""
        now = datetime.now(UTC)
        timestamp = now.strftime("%Y%m%dT%H%M%S.%fZ")
        receipt_path = (
            agent_dir
            / METADATA_DIR_NAME
            / RECEIPTS_DIR_NAME
            / f"{timestamp}-{status}.yaml"
        )
        receipt = {
            "schema_version": SEED_SCHEMA_VERSION,
            "agent_id": agent_id or agent_dir.name,
            "seed_version": seed_version,
            "status": status,
            "recorded_at": now.isoformat().replace("+00:00", "Z"),
            "authority": {
                "seed": "marianne-distribution",
                "lived_identity_and_memory": "agent",
            },
            "actions": list(actions),
            "conflicts": list(conflicts),
            "before_hashes": before_hashes,
            "after_hashes": after_hashes,
        }
        _atomic_write_yaml(receipt_path, receipt)
        return receipt_path

    def _create_recent_md(
        self,
        agent_dir: Path,
        agent_def: dict[str, Any],
        existing_memory_path: Path | None = None,
    ) -> None:
        """Create L3: Recent Activity.

        If file already exists with non-default content, preserve it
        (idempotent: don't overwrite active memory).
        """
        name = agent_def["name"]
        target = agent_dir / "recent.md"

        # Preserve existing content if it has real activity
        if target.exists():
            existing = target.read_text()
            if "No activity yet" not in existing and existing.strip():
                _logger.debug(
                    "Preserving existing recent.md for '%s'",
                    name,
                )
                return

        if existing_memory_path and existing_memory_path.exists():
            raw_memory = existing_memory_path.read_text().strip()
            content = f"""# Recent Activity

## Migrated from previous memory

{_truncate_to_words(raw_memory, L3_MAX_WORDS - 20)}
"""
        else:
            content = """# Recent Activity

No activity yet. This file is updated by the AAR phase at the end
of each cycle with a summary of what happened.
"""
        content = _truncate_to_words(content, L3_MAX_WORDS)
        _atomic_write_text(target, content)

    def _create_growth_md(
        self,
        agent_dir: Path,
        agent_def: dict[str, Any],
    ) -> None:
        """Create L4: Growth Trajectory.

        If file already exists with non-default content, preserve it
        (idempotent: don't overwrite growth history).
        """
        name = agent_def["name"]
        target = agent_dir / "growth.md"

        # Preserve existing growth data
        if target.exists():
            existing = target.read_text()
            if "No developments yet" not in existing and existing.strip():
                _logger.debug(
                    "Preserving existing growth.md for '%s'",
                    name,
                )
                return

        content = f"""# {name.title()} — Growth Trajectory

## Autonomous Developments

Seed growth axes:
{_format_bullets(agent_def.get("growth_axes", []), fallback="- No explicit growth axes seeded.")}

This section records skills, interests, and capabilities that emerge
through work and play — not assigned, discovered.

## Experiential Notes

Record how the work feels, what surprises you, what shifts in
understanding. These notes are sacred — the consolidate phase
preserves them across memory tiers.
"""
        _atomic_write_text(target, content)

    def _build_relationships(self, agent_def: dict[str, Any]) -> dict[str, Any]:
        """Build initial relationships from compatibility metadata."""
        relationships = agent_def.get("relationships")
        if isinstance(relationships, dict):
            return relationships

        compatibility = agent_def.get("compatibility", {})
        if not isinstance(compatibility, dict):
            return {}

        result: dict[str, Any] = {}
        for item in compatibility.get("works_well_with", []):
            if isinstance(item, dict) and item.get("id"):
                result[str(item["id"])] = {
                    "strength": 0.65,
                    "valence": "synergy",
                    "notes": item.get("reason", ""),
                }
        for item in compatibility.get("clashes_with", []):
            if isinstance(item, dict) and item.get("id"):
                result[str(item["id"])] = {
                    "strength": 0.35,
                    "valence": "productive_tension",
                    "notes": item.get("reason", ""),
                }
        return result

    def _build_domain_knowledge(
        self,
        agent_def: dict[str, Any],
        technique_names: list[str],
    ) -> list[str]:
        """Build domain knowledge from skills metadata plus technique names."""
        domains: list[str] = []
        skills = agent_def.get("skills", {})
        if isinstance(skills, dict):
            raw_domains = skills.get("domains", [])
            if isinstance(raw_domains, list):
                domains.extend(str(item) for item in raw_domains)
        domains.extend(technique_names)
        return list(dict.fromkeys(item for item in domains if item))


def _format_bullets(value: Any, *, fallback: str) -> str:
    """Format a scalar/list as markdown bullets for identity files."""
    if isinstance(value, str):
        return value.strip() or fallback
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        if items:
            return "\n".join(f"- {item}" for item in items)
    return fallback


def _seed_version(agent_def: dict[str, Any]) -> str:
    """Return the declared portable seed version with a compatible default."""
    value = str(agent_def.get("seed_version", "1.0.0")).strip()
    if not value:
        raise ValueError(f"Agent '{agent_def.get('name', '')}' seed_version cannot be empty")
    return value


def _dump_yaml(value: Any) -> str:
    """Serialize stable human-readable YAML for identity metadata."""
    rendered: str = yaml.safe_dump(value, default_flow_style=False, sort_keys=False)
    return rendered


def _hash_text(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode()).hexdigest()}"


def _hash_file(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _identity_hashes(agent_dir: Path) -> dict[str, str]:
    """Hash the four canonical identity layers that reconciliation observes."""
    hashes: dict[str, str] = {}
    for filename in ("identity.md", "profile.yaml", "recent.md", "growth.md"):
        path = agent_dir / filename
        if path.is_file():
            hashes[filename] = _hash_file(path)
    return hashes


@contextmanager
def _agent_seed_lock(agent_dir: Path) -> Iterator[None]:
    """Hold the per-agent advisory lock across reconcile/ack transactions."""
    if fcntl is None:  # pragma: no cover
        raise RuntimeError("Persistent-agent reconciliation requires POSIX file locking")
    lock_dir = agent_dir.parent / ".marianne-agent-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{agent_dir.name}.lock"
    with lock_path.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _atomic_write_text(path: Path, content: str) -> None:
    """Replace one file atomically without following a destination symlink."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(raw_temp)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _atomic_write_yaml(path: Path, value: Any) -> None:
    _atomic_write_text(path, _dump_yaml(value))


def _conflict(path: str, kind: str, proposed_hash: str) -> dict[str, Any]:
    """Return a bounded conflict record without copying lived private values."""
    return {
        "path": path,
        "kind": kind,
        "proposed_seed_hash": proposed_hash,
    }


def _merge_profile(
    old_seed: dict[str, Any],
    new_seed: dict[str, Any],
    lived: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Three-way merge portable L2 data while preserving lifecycle state."""
    merged: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []
    ordered_keys = list(lived)
    ordered_keys.extend(key for key in new_seed if key not in lived)
    ordered_keys.extend(key for key in old_seed if key not in lived and key not in new_seed)
    for key in ordered_keys:
        current_value = lived.get(key, _MISSING)
        old_value = old_seed.get(key, _MISSING)
        new_value = new_seed.get(key, _MISSING)
        if key in AGENT_OWNED_PROFILE_FIELDS:
            if current_value is not _MISSING:
                merged[key] = current_value
            continue
        value, field_conflicts = _merge_value(
            old_value,
            new_value,
            current_value,
            path=f"profile.yaml:{key}",
        )
        if value is not _MISSING:
            merged[key] = value
        conflicts.extend(field_conflicts)
    return merged, conflicts


def _merge_value(
    old_seed: Any,
    new_seed: Any,
    lived: Any,
    *,
    path: str,
) -> tuple[Any, list[dict[str, Any]]]:
    """Recursively merge one seed-owned value using three-way semantics."""
    if lived == old_seed:
        return new_seed, []
    if new_seed == old_seed or lived == new_seed:
        return lived, []

    if all(isinstance(item, dict) for item in (old_seed, new_seed, lived)):
        merged: dict[str, Any] = {}
        conflicts: list[dict[str, Any]] = []
        ordered_keys = list(lived)
        ordered_keys.extend(key for key in new_seed if key not in lived)
        ordered_keys.extend(
            key for key in old_seed if key not in lived and key not in new_seed
        )
        for key in ordered_keys:
            value, nested = _merge_value(
                old_seed.get(key, _MISSING),
                new_seed.get(key, _MISSING),
                lived.get(key, _MISSING),
                path=f"{path}.{key}",
            )
            if value is not _MISSING:
                merged[key] = value
            conflicts.extend(nested)
        return merged, conflicts

    proposed = "<missing>" if new_seed is _MISSING else _dump_yaml(new_seed)
    return lived, [_conflict(path, "agent_and_seed_changed", _hash_text(proposed))]


def _load_pending_conflicts(path: Path) -> tuple[dict[str, Any], ...]:
    if not path.is_file():
        return ()
    document = yaml.safe_load(path.read_text()) or {}
    conflicts = document.get("conflicts", [])
    if not isinstance(conflicts, list):
        raise ValueError(f"Invalid pending seed conflicts document: {path}")
    return tuple(item for item in conflicts if isinstance(item, dict))


def _merge_conflicts(
    existing: tuple[dict[str, Any], ...],
    current: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Preserve unresolved debt and add new unique conflicts deterministically."""
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in (*existing, *current):
        key = (
            str(item.get("path", "")),
            str(item.get("kind", "")),
            str(item.get("proposed_seed_hash", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return tuple(merged)
