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

import logging
from pathlib import Path
from typing import Any

import yaml

_logger = logging.getLogger(__name__)

DEFAULT_AGENTS_DIR = Path.home() / ".marianne" / "agents"

# Token budget enforcement (word counts as proxy)
L1_MAX_WORDS = 900
L2_MAX_WORDS = 1500
L3_MAX_WORDS = 1500


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

    The seeder is idempotent: running it on an existing agent directory
    updates files without corrupting existing identity data. Existing
    content in L3 (recent) and L4 (growth) is preserved if present.
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
        voice = agent_def.get("voice", "")
        focus = agent_def.get("focus", "")

        if not voice:
            raise ValueError(f"Agent '{name}' must have a 'voice'")
        if not focus:
            raise ValueError(f"Agent '{name}' must have a 'focus'")

        agent_dir: Path = self.agents_dir / str(name)
        agent_dir.mkdir(parents=True, exist_ok=True)
        archive_dir = agent_dir / "archive"
        archive_dir.mkdir(exist_ok=True)

        self._create_identity_md(agent_dir, agent_def, existing_meditation_path)
        self._create_profile_yaml(agent_dir, agent_def)
        self._create_recent_md(agent_dir, agent_def, existing_memory_path)
        self._create_growth_md(agent_dir, agent_def)

        _logger.info("Agent '%s' identity seeded at %s", name, agent_dir)
        return agent_dir

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

    def _create_identity_md(
        self,
        agent_dir: Path,
        agent_def: dict[str, Any],
        existing_meditation_path: Path | None = None,
    ) -> None:
        """Create L1: Persona Core + resurrection protocol."""
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
        content = _truncate_to_words(content, L1_MAX_WORDS)
        (agent_dir / "identity.md").write_text(content)

    def _create_profile_yaml(
        self,
        agent_dir: Path,
        agent_def: dict[str, Any],
    ) -> None:
        """Create L2: Extended Profile."""
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

        yaml_content = yaml.dump(profile, default_flow_style=False, sort_keys=False)
        if _count_words(yaml_content) > L2_MAX_WORDS:
            _logger.warning(
                "Agent '%s' L2 profile exceeds %d word budget (%d words)",
                name,
                L2_MAX_WORDS,
                _count_words(yaml_content),
            )
        (agent_dir / "profile.yaml").write_text(yaml_content)

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
        target.write_text(content)

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
        target.write_text(content)

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
