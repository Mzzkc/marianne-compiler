"""Bound and installed scores must not carry this machine's home layout."""

from __future__ import annotations

import subprocess
from pathlib import Path

import jinja2
import pytest
import yaml
from typer.testing import CliRunner

from marianne_compiler.agent_cli import app
from marianne_compiler.agent_package import generate_agent_package, install_agent_package
from marianne_compiler.portable_paths import (
    home_aliases,
    portabilize_score,
    remaining_absolute,
)

runner = CliRunner()
REAL_AGENTS = Path("/home/emzinox/Projects/AGENTS/agents")


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    real = tmp_path / "realhome"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real)
    monkeypatch.setenv("HOME", str(real))
    (real / "Projects" / "AGENTS" / "agents" / "canyon").mkdir(parents=True)
    (real / ".marianne").mkdir()
    (real / ".marianne" / "agents").symlink_to(real / "Projects" / "AGENTS" / "agents")
    return real


def _score(agents_root: str, name: str = "canyon") -> dict:
    d = f"{agents_root}/{name}"
    return {
        "workspace": "/tmp/ws",
        "sheet": {
            "prelude": [{"file": f"{d}/identity.md", "as": "context", "required": True}],
            "cadenzas": {1: [{"directory": f"{d}/cadenzas/personal/active", "as": "context"}]},
        },
        "prompt": {
            "template": 'AGENT_DIR="{{ agent_identity_dir }}"\n',
            "variables": {"agent_identity_dir": d},
        },
        "validations": [
            {"type": "file_exists", "path": f"{d}/.marianne/debt.yaml"},
            {
                "type": "command_succeeds",
                "command": (
                    f'CADENZA_DIR="{d}/cadenzas/personal/active" '
                    f"RECENT={d}/recent.md SNAP={{workspace}}/s "
                    "bash -c 'test -d \"$CADENZA_DIR\" && test -f \"$RECENT\"'"
                ),
            },
        ],
        "techniques": {
            "x": {"config": {"path": f"{agents_root.rsplit('/', 1)[0]}/techniques/x.md"}},
        },
    }


def test_agents_tree_under_home_becomes_canonical_tilde_root_even_via_alias(
    home: Path, tmp_path: Path,
) -> None:
    alias = tmp_path / "alias"
    agents = home / "Projects" / "AGENTS" / "agents"
    score = _score(f"{alias}/Projects/AGENTS/agents")
    portable, warnings = portabilize_score(score, agents)
    assert warnings == []
    text = yaml.safe_dump(portable)
    assert str(home) not in text and str(alias) not in text
    assert portable["sheet"]["prelude"][0]["file"] == "~/.marianne/agents/canyon/identity.md"
    assert portable["prompt"]["variables"]["agent_identity_dir"] == "~/.marianne/agents/canyon"
    assert portable["techniques"]["x"]["config"]["path"] == "~/Projects/AGENTS/techniques/x.md"
    assert remaining_absolute(portable, *home_aliases(score)) == 0


def test_shell_commands_get_home_not_tilde_and_still_run(home: Path) -> None:
    agents = home / "Projects" / "AGENTS" / "agents"
    (agents / "canyon" / "cadenzas" / "personal" / "active").mkdir(parents=True)
    (agents / "canyon" / "recent.md").write_text("x")
    portable, _ = portabilize_score(_score(str(agents)), agents)
    command = portable["validations"][1]["command"]
    assert "~" not in command
    assert 'CADENZA_DIR="$HOME/.marianne/agents/canyon/cadenzas/personal/active"' in command
    assert 'RECENT="$HOME/.marianne/agents"/canyon/recent.md' in command
    ws = home / "w"
    ws.mkdir()
    proc = subprocess.run(
        ["bash", "-c", command.replace("{workspace}", str(ws))],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    # The same command still resolves from a different home that holds the agents.
    elsewhere = home.parent / "otherhome"
    (elsewhere / ".marianne").mkdir(parents=True)
    (elsewhere / ".marianne" / "agents").symlink_to(agents)
    proc = subprocess.run(
        ["bash", "-c", command.replace("{workspace}", str(ws))],
        env={"HOME": str(elsewhere), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_template_agent_dir_assignment_renders_to_home(home: Path) -> None:
    agents = home / "Projects" / "AGENTS" / "agents"
    portable, _ = portabilize_score(_score(str(agents)), agents)
    out = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(
        portable["prompt"]["template"]
    ).render(**portable["prompt"]["variables"])
    assert out == 'AGENT_DIR="$HOME/.marianne/agents/canyon"'


def test_heredoc_and_single_quoted_occurrences_are_left_and_reported(home: Path) -> None:
    agents = home / "Projects" / "AGENTS" / "agents"
    d = f"{agents}/canyon"
    score = {
        "validations": [
            {"type": "command_succeeds", "command": f"python - <<'PY'\nP = '{d}/x'\nPY"},
            {"type": "command_succeeds", "command": f"X='{d}/x' true"},
        ]
    }
    portable, warnings = portabilize_score(score, agents)
    assert portable["validations"][0]["command"] == score["validations"][0]["command"]
    assert portable["validations"][1]["command"] == score["validations"][1]["command"]
    assert any("remain" in w for w in warnings)


def test_agents_dir_outside_home_stays_absolute_with_warning(home: Path, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere" / "agents"
    portable, warnings = portabilize_score(_score(str(outside)), outside)
    assert portable["prompt"]["variables"]["agent_identity_dir"] == f"{outside}/canyon"
    assert any("outside the home directory" in w for w in warnings)


def test_install_writes_portable_scores_for_a_new_install(
    home: Path, tmp_path: Path,
) -> None:
    techniques = tmp_path / "tech"
    techniques.mkdir()
    (techniques / "identity.md").write_text("# Identity\n")
    config = {
        "project": {"name": "p"},
        "defaults": {
            "techniques": {"identity": {"kind": "skill", "phases": ["all"]}},
            "instruments": {"work": {"primary": {"instrument": "claude-code"}}},
        },
        "agents": [{"name": "canyon", "voice": "v", "focus": "f"}],
    }
    package = tmp_path / "package"
    generate_agent_package(config, package, techniques_dir=techniques)
    agents = home / "Projects" / "AGENTS" / "agents"
    report = install_agent_package(
        package, techniques_source=techniques, agents_dir=agents,
        techniques_dir=home / ".marianne" / "techniques",
    )
    assert "warnings" not in report
    for shape in ("full-lifecycle", "targeted-work", "lifecycle-integration"):
        text = (agents / "canyon" / "scores" / f"{shape}.yaml").read_text()
        assert str(home) not in text, shape
        assert "~/.marianne/agents/canyon" in text


def _inventory(path: Path) -> None:
    path.write_text(yaml.safe_dump({
        "schema_version": 1,
        "profiles": [{
            "name": "verified", "provider": "anthropic", "model": "claude-opus-5-5",
            "available": True, "invocation_contract_verified": True,
            "entitlement_verified": True, "verified_at": "2026-10-20T00:00:00Z",
            "capabilities": ["file_editing"], "context_tokens": 200000,
            "reliability_class": "high", "latency_class": "normal",
            "metered_cost": "subscription", "priority": 1,
            "evidence": ["2026-10-20T00:00:00Z checked"],
        }],
    }))


@pytest.mark.skipif(not (REAL_AGENTS / "harper" / "scores").is_dir(), reason="no real agents")
def test_bound_harper_has_no_absolute_home_and_passes_v004(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marianne.core.config import JobConfig
    from marianne.validation.checks.paths import AbsoluteHomePathCheck

    inventory = tmp_path / "inv.yaml"
    _inventory(inventory)
    # Harper's recorded phases need more than the one-profile fixture offers;
    # bind the real score against the real phase requirements instead.
    real_inventory = Path(
        "/home/emzinox/Projects/SCORES/candidate-advantage/restart-20261106/"
        "live-builder-route-inventory-20261116.yaml"
    )
    if not real_inventory.is_file():
        pytest.skip("route inventory fixture absent")
    task = tmp_path / "t.md"
    task.write_text("do it\n")
    runs = tmp_path / "runs"
    result = runner.invoke(app, [
        "engage", "harper", "--shape", "targeted-work", "--defer-lifecycle",
        "--accept-debt", "--purpose", "p", "--inventory", str(real_inventory),
        "--runs-dir", str(runs), "--agents-dir", str(REAL_AGENTS), "--task", str(task),
        "--date", "20261116", "--evidence-at", "2026-11-16T15:00:00Z",
    ])
    assert result.exit_code == 0, result.output
    out = runs / "harper-p-20261116" / "targeted-work-harper-p-20261116.yaml"
    text = out.read_text()
    assert "/home/emzi" not in text
    config = JobConfig.from_yaml(out)
    issues = AbsoluteHomePathCheck().check(config, out, text)
    assert issues == []
