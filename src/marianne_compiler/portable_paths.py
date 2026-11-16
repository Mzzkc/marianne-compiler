"""Rewrite machine-absolute home paths in a score into forms that survive a move.

The conductor reads paths two different ways, so there are two target forms:

* Wherever the runtime itself reads a path (injection ``file``/``directory``,
  validation ``path``, technique ``config.path``, ``workspace``, template
  variables) it expands ``~``; ``~/...`` is also what V004 accepts.
* Inside a shell ``command`` a *quoted* ``"~/x"`` is NOT expanded by bash, so
  there the portable form is ``$HOME`` (double-quote context) or ``"$HOME"``
  (bare word). A single-quoted or heredoc occurrence cannot be rewritten safely
  and is left alone and reported.

A home directory is often reached through a symlinked alias (``/home/emzi`` ->
``/home/emzinox``), so aliases are discovered from the score text itself: any
``/home/<name>`` that resolves to the real home counts as the home.

The agents tree is rewritten first, to the canonical public root
``~/.marianne/agents`` when that resolves to the same directory (the root the
package generator already advertises) and otherwise to its home-relative path.
An agents tree outside the home is left absolute and reported as a warning.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

CANONICAL_AGENTS_ROOT = "~/.marianne/agents"

_ABS_PATH = re.compile(r"(?<![\w/.~$-])/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*")
# A prefix must begin a path: not glued onto a longer path, variable or option.
_LOOKBEHIND = r"(?<![\w/.~$-])"
_LOOKAHEAD = r"(?![\w.-])"
_SAFE_REL = re.compile(r"^[A-Za-z0-9@%+=:,./_-]+$")
_SKIP_KEYS = frozenset({"routing_receipts"})


def home_aliases(value: Any, *, home: Path | None = None) -> list[str]:
    """Absolute spellings of the home directory: the real one plus symlink aliases."""
    real_home = Path(home) if home is not None else Path.home()
    resolved = os.path.realpath(real_home)
    found = {str(real_home), resolved}
    seen: dict[str, bool] = {}
    for text in _strings(value):
        for match in _ABS_PATH.finditer(text):
            parts = match.group(0).split("/")[1:]
            for depth in range(1, min(len(parts), 6) + 1):
                candidate = "/" + "/".join(parts[:depth])
                if candidate not in seen:
                    seen[candidate] = os.path.realpath(candidate) == resolved
                if seen[candidate]:
                    found.add(candidate)
    return sorted(found, key=len, reverse=True)


def agents_root_spelling(agents_dir: Path, *, home: Path | None = None) -> str | None:
    """The portable spelling of the agents tree, or None if it is outside the home."""
    real_home = Path(os.path.realpath(home if home is not None else Path.home()))
    real_agents = Path(os.path.realpath(agents_dir.expanduser()))
    if real_agents == Path(os.path.realpath(real_home / ".marianne" / "agents")):
        return CANONICAL_AGENTS_ROOT
    try:
        rel = real_agents.relative_to(real_home).as_posix()
    except ValueError:
        return None
    if rel == "." or not _SAFE_REL.match(rel):
        return None
    return f"~/{rel}"


def portabilize_score(
    score: dict[str, Any],
    agents_dir: Path,
    *,
    home: Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Return ``(portable copy of score, warnings)``; the input is not modified."""
    warnings: list[str] = []
    real_home = os.path.realpath(home if home is not None else Path.home())
    aliases = home_aliases(score, home=home)
    rules: list[tuple[re.Pattern[str], str]] = []

    spelling = agents_root_spelling(agents_dir, home=home)
    real_agents = os.path.realpath(agents_dir.expanduser())
    if spelling is None:
        warnings.append(
            f"agents dir {real_agents} is outside the home directory {real_home}; "
            "its paths stay absolute and the bound score is not portable"
        )
    else:
        rel = os.path.relpath(real_agents, real_home)
        prefixes = {real_agents, str(agents_dir.expanduser())}
        prefixes.update(f"{alias}/{rel}" for alias in aliases)
        rules.append((_prefix_regex(sorted(prefixes, key=len, reverse=True)), spelling))
    rules.append((_prefix_regex(aliases), "~"))

    portable = _walk(score, rules, shell=False)
    portable = _patch_template_for_shell(portable)
    left = remaining_absolute(portable, *aliases)
    if left:
        warnings.append(
            f"{left} absolute home-path occurrence(s) remain (single-quoted shell "
            "words or heredoc bodies cannot be rewritten safely)"
        )
    return portable, warnings


def remaining_absolute(score: Any, *prefixes: str) -> int:
    """Occurrences of the absolute directory ``prefixes`` still in ``score``."""
    regex = _prefix_regex(list(prefixes))
    return sum(len(regex.findall(text)) for text in _strings(score))


def _prefix_regex(prefixes: list[str]) -> re.Pattern[str]:
    body = "|".join(re.escape(p.rstrip("/")) for p in prefixes)
    return re.compile(_LOOKBEHIND + "(?:" + body + ")" + _LOOKAHEAD)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


def _walk(value: Any, rules: list[tuple[re.Pattern[str], str]], *, shell: bool) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                item if key in _SKIP_KEYS
                else _walk(item, rules, shell=shell or key == "command")
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_walk(item, rules, shell=shell) for item in value]
    if isinstance(value, str):
        for regex, target in rules:
            value = _rewrite(value, regex, target, shell=shell)
        return value
    return value


def _rewrite(text: str, regex: re.Pattern[str], target: str, *, shell: bool) -> str:
    if not shell:
        return regex.sub(lambda _m: target, text)
    shell_target = target.replace("~", "$HOME", 1)

    def replace(match: re.Match[str]) -> str:
        start = match.start()
        if "<<" in text[:start]:
            return match.group(0)  # heredoc body: literal data, not shell words
        before = text[start - 1] if start else ""
        if before == '"':
            return shell_target  # already inside double quotes: $HOME expands
        if before in ("", "=", " ", "\t", "\n", "(", ";"):
            return f'"{shell_target}"'  # bare word: quote the expansion
        return match.group(0)  # single quotes etc.: cannot rewrite safely

    return regex.sub(replace, text)


def _patch_template_for_shell(score: dict[str, Any]) -> dict[str, Any]:
    """Keep ``AGENT_DIR="{{ agent_identity_dir }}"`` working once the variable is ``~/..``.

    The template assigns the variable inside double quotes in deterministic bash
    sheets, where bash does not expand a tilde. Expanding it to ``$HOME`` at
    render time keeps one source of truth for the directory.
    """
    prompt = score.get("prompt")
    if not isinstance(prompt, dict) or not isinstance(prompt.get("template"), str):
        return score
    old = 'AGENT_DIR="{{ agent_identity_dir }}"'
    new = 'AGENT_DIR="{{ agent_identity_dir | replace(\'~\', \'$HOME\', 1) }}"'
    prompt["template"] = prompt["template"].replace(old, new)
    return score


