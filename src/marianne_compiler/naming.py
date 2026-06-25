"""Naming helpers for generated score artifacts."""

from __future__ import annotations

from typing import Any


def job_name_prefix(defaults: dict[str, Any]) -> str:
    """Return the configured score/job prefix.

    The prefix is used for generated score filenames and top-level score
    names, not for the agent's identity or prompt variables.
    """
    raw = defaults.get("job_name_prefix", "")
    if raw is None:
        return ""
    prefix = str(raw).strip()
    if not prefix:
        return ""
    if any(sep in prefix for sep in ("/", "\\")) or any(
        char.isspace() for char in prefix
    ):
        raise ValueError(
            "defaults.job_name_prefix must not contain whitespace or path separators"
        )
    return prefix


def score_file_stem(agent_name: str, defaults: dict[str, Any]) -> str:
    """Return the generated score file stem for an agent."""
    return f"{job_name_prefix(defaults)}{agent_name}"
