"""Technique wirer — lowers compiler technique declarations.

Reads agent technique declarations and:
- Builds per-phase technique manifests for generated prompts
- Emits runtime ``techniques:`` declarations with skill document paths
- Configures MCP server access per phase through runtime declarations
- Wires A2A agent card metadata

Each phase, the agent receives a technique manifest telling them what
tools are available right now. The baton runtime is responsible for resolving
active techniques and injecting skill documents exactly once at sheet dispatch.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from marianne_compiler.sheets import PHASE_MAP, SHEET_PHASE, SHEETS_PER_CYCLE

_logger = logging.getLogger(__name__)


class TechniqueWirer:
    """Wires technique declarations into prompts and runtime declarations.

    Reads agent technique configs and produces:
    1. Technique manifests (markdown) per phase
    2. Runtime technique declarations with explicit skill document paths
    3. A2A agent card config for registration
    """

    def __init__(self, techniques_dir: Path | None = None) -> None:
        """Initialize the technique wirer.

        Args:
            techniques_dir: Directory containing technique module documents.
                Falls back to searching common locations if not specified.
        """
        self.techniques_dir = techniques_dir

    def wire(
        self,
        agent_def: dict[str, Any],
        defaults: dict[str, Any],
        *,
        workspace: str = "",
    ) -> dict[str, Any]:
        """Wire techniques for an agent, returning cadenza additions and A2A config.

        Args:
            agent_def: Agent definition with optional ``techniques`` and
                ``a2a_skills`` fields.
            defaults: Global defaults with technique declarations.
            workspace: Workspace path for manifest output.

        Returns:
            Dict with keys:
                ``cadenzas``: empty compatibility mapping; runtime technique
                    injection owns skill-document loading.
                ``agent_card``: dict | None — A2A agent card if a2a_skills defined
                ``technique_manifests``: dict[int, str] — per-sheet manifest text
        """
        # Merge default techniques with agent-specific overrides
        merged_techniques = dict(defaults.get("techniques", {}))
        agent_techniques = agent_def.get("techniques", {})
        if isinstance(agent_techniques, dict):
            merged_techniques.update(agent_techniques)

        manifests: dict[int, str] = {}

        # Generate per-sheet technique manifests
        for sheet_num in range(1, SHEETS_PER_CYCLE + 1):
            phase = SHEET_PHASE.get(sheet_num, "")
            active_techniques = self._get_active_techniques(
                merged_techniques, phase
            )
            if active_techniques:
                manifest = self._generate_manifest(active_techniques, phase)
                manifests[sheet_num] = manifest

        # Build A2A agent card
        agent_card = self._build_agent_card(agent_def)

        return {
            "cadenzas": {},
            "agent_card": agent_card,
            "technique_manifests": manifests,
            "runtime_techniques": self._build_runtime_techniques(merged_techniques),
        }

    def _get_active_techniques(
        self,
        techniques: dict[str, Any],
        phase: str,
    ) -> dict[str, dict[str, Any]]:
        """Return techniques active in the given phase."""
        active: dict[str, dict[str, Any]] = {}
        for name, config in techniques.items():
            if not isinstance(config, dict):
                continue
            phases = config.get("phases", [])
            if phase in phases or "all" in phases:
                active[name] = config
        return active

    def _generate_manifest(
        self,
        active_techniques: dict[str, dict[str, Any]],
        phase: str,
    ) -> str:
        """Generate a technique manifest markdown string for a phase.

        The manifest tells the agent what tools are available right now.
        """
        sections: list[str] = [f"## Techniques Available — {phase} phase\n"]

        mcp_techniques: list[tuple[str, dict[str, Any]]] = []
        protocol_techniques: list[tuple[str, dict[str, Any]]] = []
        skill_techniques: list[tuple[str, dict[str, Any]]] = []

        for name, config in active_techniques.items():
            kind = config.get("kind", "skill")
            if kind == "mcp":
                mcp_techniques.append((name, config))
            elif kind == "protocol":
                protocol_techniques.append((name, config))
            else:
                skill_techniques.append((name, config))

        if mcp_techniques:
            sections.append("### MCP Tools")
            for name, config in mcp_techniques:
                desc = config.get("config", {}).get("description", f"{name} MCP server")
                sections.append(f"- **{name}**: {desc}")
            sections.append("")

        if protocol_techniques:
            sections.append("### Protocols")
            for name, config in protocol_techniques:
                if name == "a2a":
                    sections.append(
                        "- **A2A**: Discover running agents, delegate tasks, check inbox"
                    )
                else:
                    desc = config.get("config", {}).get("description", name)
                    sections.append(f"- **{name}**: {desc}")
            sections.append("")

        if skill_techniques:
            sections.append("### Skills")
            for name, config in skill_techniques:
                desc = config.get("config", {}).get("description", name)
                sections.append(f"- **{name}**: {desc}")
            sections.append("")

        return "\n".join(sections)

    def _find_technique_doc(self, technique_name: str) -> Path | None:
        """Find the technique document for a named technique.

        Searches the techniques directory for matching .md files.
        """
        if not self.techniques_dir:
            return None

        # Try exact match first, then with common suffixes
        candidates = [
            self.techniques_dir / f"{technique_name}.md",
            self.techniques_dir / technique_name / "SKILL.md",
            self.techniques_dir / f"{technique_name}-protocol.md",
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate

        return None

    def _build_agent_card(self, agent_def: dict[str, Any]) -> dict[str, Any] | None:
        """Build A2A agent card from agent definition."""
        a2a_skills = agent_def.get("a2a_skills", [])
        if not a2a_skills:
            return None

        name = agent_def["name"]
        focus = agent_def.get("focus", "")
        voice = agent_def.get("voice", "")

        return {
            "name": name,
            "description": f"{focus} — {voice}" if voice else focus,
            "skills": [
                {"id": s["id"], "description": s.get("description", "")}
                for s in a2a_skills
                if isinstance(s, dict) and "id" in s
            ],
        }

    def _build_runtime_techniques(
        self,
        techniques: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        """Build top-level runtime technique declarations for JobConfig.

        The baton currently resolves active techniques using the sheet's
        movement value, which is numeric for compiler-generated scores.
        Preserve semantic phase names for readability, and add concrete sheet
        numbers as strings so runtime A2A/MCP resolution can match.
        """
        runtime: dict[str, dict[str, Any]] = {}
        for name, config in techniques.items():
            if not isinstance(config, dict):
                continue

            item = dict(config)
            phases = item.get("phases", [])
            expanded: list[str] = []
            seen: set[str] = set()
            for phase in phases:
                phase_str = str(phase)
                if phase_str not in seen:
                    expanded.append(phase_str)
                    seen.add(phase_str)
                for sheet_num in PHASE_MAP.get(phase_str, []):
                    sheet_str = str(sheet_num)
                    if sheet_str not in seen:
                        expanded.append(sheet_str)
                        seen.add(sheet_str)

            item["phases"] = expanded

            if item.get("kind", "skill") == "skill":
                item["required"] = bool(item.get("required", True))
                doc = self._find_technique_doc(name)
                if doc:
                    cfg = dict(item.get("config", {}))
                    cfg.setdefault("path", str(doc))
                    item["config"] = cfg

            runtime[name] = item

        return runtime
