"""Tests for portable persistent-agent maintenance commands."""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from marianne_compiler.agent_cli import app
from marianne_compiler.identity import IdentitySeeder

runner = CliRunner()


def test_reconcile_command_dry_run_is_read_only(tmp_path: Path) -> None:
    agents = tmp_path / "agents"
    seeder = IdentitySeeder(agents)
    initial = {
        "name": "canyon",
        "seed_version": "1.0.0",
        "voice": "Structure persists.",
        "focus": "architecture",
        "role": "architect",
    }
    seeder.seed(initial)
    seed_path = tmp_path / "seed.yaml"
    seed_path.write_text(
        yaml.safe_dump({**initial, "seed_version": "2.0.0", "role": "co-composer"})
    )
    before = {
        path.relative_to(agents): path.read_bytes()
        for path in agents.rglob("*")
        if path.is_file()
    }

    result = runner.invoke(
        app,
        ["reconcile", str(seed_path), "--agents-dir", str(agents), "--dry-run"],
    )

    after = {
        path.relative_to(agents): path.read_bytes()
        for path in agents.rglob("*")
        if path.is_file()
    }
    assert result.exit_code == 0, result.output
    assert "would_update" in result.output
    assert before == after


def test_census_command_emits_read_only_report(tmp_path: Path) -> None:
    agents = tmp_path / "agents"
    IdentitySeeder(agents).seed(
        {"name": "canyon", "voice": "v", "focus": "f"}
    )

    result = runner.invoke(
        app,
        ["census", "--canonical-root", str(agents), "--search-root", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    report = yaml.safe_load(result.output)
    assert report["mode"] == "read_only"
    assert report["canonical"][0]["agent_id"] == "canyon"


def test_bind_score_routes_refuses_overwriting_managed_source(tmp_path: Path) -> None:
    score = tmp_path / "score.yaml"
    score.write_text("name: score\n")
    inventory = tmp_path / "inventory.yaml"
    inventory.write_text("profiles: []\n")

    result = runner.invoke(
        app,
        [
            "bind-score-routes",
            str(score),
            str(inventory),
            "--output",
            str(score),
        ],
    )

    assert result.exit_code != 0
    assert "separate run artifact" in result.output


def _installed_agent(tmp_path: Path, shape: str) -> tuple[Path, Path]:
    agents = tmp_path / "agents"
    scores = agents / "canyon" / "scores"
    scores.mkdir(parents=True)
    score = {
        "name": f"{shape}-canyon",
        "workspace": "/REQUIRES-LIVE-BINDING",
        "instrument": "stale",
        "instrument_fallbacks": [],
        "sheet": {"per_sheet_instruments": {}, "per_sheet_fallbacks": {}},
        "prompt": {
            "variables": {
                "marianne_agent": {
                    "schema_version": 1,
                    "agent_id": "canyon",
                    "score_shape": shape,
                    "phase_requirements": {
                        "work": {"required_capabilities": ["file_editing"], "load_bearing": True}
                    },
                    "routing_receipts": {},
                }
            }
        },
    }
    (scores / f"{shape}.yaml").write_text(yaml.safe_dump(score, sort_keys=False))
    inventory = tmp_path / "inventory.yaml"
    inventory.write_text(yaml.safe_dump({
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
    return agents, inventory


def test_engage_binds_names_and_workspaces_in_one_step(tmp_path: Path) -> None:
    agents, inventory = _installed_agent(tmp_path, "full-lifecycle")
    runs = tmp_path / "runs"
    result = runner.invoke(app, [
        "engage", "canyon", "--purpose", "Morning-Cut", "--inventory", str(inventory),
        "--runs-dir", str(runs), "--agents-dir", str(agents), "--date", "20261020",
        "--evidence-at", "2026-10-20T10:00:00Z",
    ])
    assert result.exit_code == 0, result.output
    engagement = runs / "canyon-morning-cut-20261020"
    output = engagement / "full-lifecycle-canyon-morning-cut-20261020.yaml"
    assert output.is_file()
    bound = yaml.safe_load(output.read_text())
    assert bound["name"] == "full-lifecycle-canyon-morning-cut-20261020"
    assert bound["workspace"] == str(engagement)
    assert bound["instrument"] == "verified--claude-opus-5-5" or "verified" in bound["instrument"]
    assert f"run: mzt run {output}" in result.output
    # The installed score is untouched.
    installed = yaml.safe_load((agents / "canyon" / "scores" / "full-lifecycle.yaml").read_text())
    assert installed["instrument"] == "stale"
    # A second engage with the same purpose on the same day is refused, not overwritten.
    again = runner.invoke(app, [
        "engage", "canyon", "--purpose", "morning-cut", "--inventory", str(inventory),
        "--runs-dir", str(runs), "--agents-dir", str(agents), "--date", "20261020",
    ])
    assert again.exit_code != 0
    assert "already bound" in again.output


def test_engage_targeted_work_needs_explicit_deferral(tmp_path: Path) -> None:
    agents, inventory = _installed_agent(tmp_path, "targeted-work")
    runs = tmp_path / "runs"
    base = [
        "engage", "canyon", "--purpose", "fix", "--inventory", str(inventory),
        "--runs-dir", str(runs), "--agents-dir", str(agents), "--shape", "targeted-work",
        "--evidence-at", "2026-10-20T10:00:00Z",
    ]
    refused = runner.invoke(app, base)
    assert refused.exit_code != 0
    assert "--defer-lifecycle" in refused.output
    assert not runs.exists()
    accepted = runner.invoke(app, [*base, "--defer-lifecycle"])
    assert accepted.exit_code == 0, accepted.output
    assert "lifecycle-integration afterwards" in accepted.output


def test_engage_default_shape_is_full_lifecycle_and_missing_score_is_named(tmp_path: Path) -> None:
    agents, inventory = _installed_agent(tmp_path, "targeted-work")  # no full-lifecycle installed
    result = runner.invoke(app, [
        "engage", "canyon", "--purpose", "x", "--inventory", str(inventory),
        "--runs-dir", str(tmp_path / "runs"), "--agents-dir", str(agents),
    ])
    assert result.exit_code != 0
    assert "full-lifecycle" in result.output and "install-package" in result.output


def _engage(tmp_path: Path, shape: str = "full-lifecycle", *extra: str):
    agents, inventory = _installed_agent(tmp_path, shape)
    runs = tmp_path / "runs"
    args = [
        "engage", "canyon", "--purpose", "job", "--inventory", str(inventory),
        "--runs-dir", str(runs), "--agents-dir", str(agents), "--date", "20261020",
        "--evidence-at", "2026-10-20T10:00:00Z", "--shape", shape, *extra,
    ]
    if shape == "targeted-work" and "--defer-lifecycle" not in extra:
        args.append("--defer-lifecycle")
    result = runner.invoke(app, args)
    engagement = runs / "canyon-job-20261020"
    out = engagement / f"{shape}-canyon-job-20261020.yaml"
    return result, engagement, out


def test_engage_task_is_copied_immutably_and_injected_as_required_prelude(
    tmp_path: Path,
) -> None:
    import hashlib
    import os
    import stat

    task = tmp_path / "brief.md"
    task.write_text("Fix the flaky test.\n")
    digest = hashlib.sha256(task.read_bytes()).hexdigest()
    result, engagement, out = _engage(tmp_path, "full-lifecycle", "--task", str(task))
    assert result.exit_code == 0, result.output
    assert f"task: {task.resolve()} sha256:{digest[:16]}" in result.output
    copy = engagement / "task-brief.md"
    assert copy.read_text() == "Fix the flaky test.\n"
    assert not os.access(copy, os.W_OK) or stat.S_IMODE(copy.stat().st_mode) == 0o444
    assert stat.S_IMODE(copy.stat().st_mode) == 0o444
    bound = yaml.safe_load(out.read_text())
    assert {
        "file": "{{ score_dir }}/task-brief.md", "as": "context", "required": True,
    } in bound["sheet"]["prelude"]
    assert str(engagement) not in str(bound["sheet"]["prelude"])
    receipt = bound["prompt"]["variables"]["marianne_agent"]["task"]
    assert receipt["copy"] == "task-brief.md"
    assert receipt["sha256"] == f"sha256:{digest}"
    # Editing the source afterwards cannot change what the engagement reads.
    task.write_text("changed")
    assert copy.read_text() == "Fix the flaky test.\n"


def test_engage_task_is_optional_and_missing_task_is_refused(tmp_path: Path) -> None:
    result, engagement, out = _engage(tmp_path)
    assert result.exit_code == 0, result.output
    bound = yaml.safe_load(out.read_text())
    assert "task" not in bound["prompt"]["variables"]["marianne_agent"]
    assert "task:" not in result.output
    assert not list(engagement.glob("task-*"))

    other = tmp_path / "other"
    other.mkdir()
    missing = _engage(other, "full-lifecycle", "--task", str(other / "nope.md"))[0]
    assert missing.exit_code != 0
    assert "--task" in missing.output
    assert not (other / "runs").exists()


def test_engage_step_and_idle_timeouts_flow_through_the_binder(tmp_path: Path) -> None:
    result, _engagement, out = _engage(
        tmp_path, "full-lifecycle", "--step-timeout", "7200", "--idle-timeout", "5400",
    )
    assert result.exit_code == 0, result.output
    bound = yaml.safe_load(out.read_text())
    contract = bound["prompt"]["variables"]["marianne_agent"]
    assert contract["execution_limits"] == {
        "step_timeout_seconds": 7200, "idle_timeout_seconds": 5400,
    }
    assert bound["stale_detection"]["idle_timeout_seconds"] == 5400
    assert contract["routing_receipts"]["work"]["selected"][0]["timeout_seconds"] == 7200
    assert all(a["config"]["timeout_seconds"] == 7200 for a in bound["instruments"].values())


def test_engage_rejects_out_of_range_timeouts_before_writing(tmp_path: Path) -> None:
    for flag, value in (("--step-timeout", "0"), ("--idle-timeout", "14401")):
        sub = tmp_path / flag.strip("-")
        sub.mkdir()
        result, engagement, _out = _engage(sub, "full-lifecycle", flag, value)
        assert result.exit_code != 0
        assert "14400" in result.output
        assert not engagement.exists()


def _write_debt(agents: Path, **fields: object) -> None:
    meta = agents / "canyon" / ".marianne"
    meta.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 1, "kind": "marianne-lifecycle-debt", "agent": "canyon",
        "status": "pending", "source_engagement": "e3", **fields,
    }
    (meta / "pending-lifecycle-debt.yaml").write_text(yaml.safe_dump(record))


def _targeted(tmp_path: Path):
    agents, inventory = _installed_agent(tmp_path, "targeted-work")
    return agents, lambda *extra: runner.invoke(app, [
        "engage", "canyon", "--purpose", "job", "--inventory", str(inventory),
        "--runs-dir", str(tmp_path / "runs"), "--agents-dir", str(agents),
        "--date", "20261020", "--evidence-at", "2026-10-20T10:00:00Z",
        "--shape", "targeted-work", "--defer-lifecycle", *extra,
    ])


def test_targeted_work_refused_at_three_pending_debts_unless_accepted(tmp_path: Path) -> None:
    agents, run = _targeted(tmp_path)
    _write_debt(agents, carried_pending_from=["e1", "e2"])
    refused = run()
    assert refused.exit_code != 0
    assert "3 pending lifecycle debts" in refused.output
    assert "--shape lifecycle-integration" in refused.output
    assert "--accept-debt" in refused.output
    assert not (tmp_path / "runs").exists()
    accepted = run("--accept-debt")
    assert accepted.exit_code == 0, accepted.output
    assert "debt: 3 pending" in accepted.output


def test_targeted_work_below_threshold_proceeds_and_debt_line_is_on_stdout(
    tmp_path: Path,
) -> None:
    agents, run = _targeted(tmp_path)
    _write_debt(agents, carried_pending_from=["e1"])
    result = run()
    assert result.exit_code == 0, result.output
    stdout_only = runner.invoke(app, [
        "engage", "canyon", "--purpose", "again", "--inventory",
        str(tmp_path / "inventory.yaml"), "--runs-dir", str(tmp_path / "runs"),
        "--agents-dir", str(agents), "--date", "20261020", "--shape", "targeted-work",
        "--defer-lifecycle", "--evidence-at", "2026-10-20T10:00:00Z",
    ])
    assert "debt: 2 pending before this run" in stdout_only.stdout
    assert "debt: 2 pending before this run" in stdout_only.stderr


def test_debt_follows_archived_prior_records_and_ignores_integrated(tmp_path: Path) -> None:
    agents, run = _targeted(tmp_path)
    older = tmp_path / "older.yaml"
    oldest = tmp_path / "oldest.yaml"
    oldest.write_text(yaml.safe_dump({"status": "pending"}))
    older.write_text(yaml.safe_dump({"status": "pending", "prior_debt_snapshot": str(oldest)}))
    _write_debt(agents, prior_debt_snapshot={"path": str(older), "sha256": "x"})
    refused = run()
    assert refused.exit_code != 0 and "3 pending lifecycle debts" in refused.output
    _write_debt(agents, status="integrated", carried_pending_from=["a", "b", "c"])
    assert run().exit_code == 0


def test_full_lifecycle_is_never_refused_for_debt(tmp_path: Path) -> None:
    agents, inventory = _installed_agent(tmp_path, "full-lifecycle")
    _write_debt(agents, carried_pending_from=["a", "b", "c", "d"])
    result = runner.invoke(app, [
        "engage", "canyon", "--purpose", "job", "--inventory", str(inventory),
        "--runs-dir", str(tmp_path / "runs"), "--agents-dir", str(agents),
        "--date", "20261020", "--evidence-at", "2026-10-20T10:00:00Z",
    ])
    assert result.exit_code == 0, result.output


def test_engage_prints_real_workspace_path_and_filesystem(tmp_path: Path) -> None:
    result, engagement, _out = _engage(tmp_path)
    assert result.exit_code == 0, result.output
    line = next(ln for ln in result.output.splitlines() if ln.startswith("workspace: "))
    assert line.startswith(f"workspace: {engagement.resolve()} (filesystem /")
    assert "WARNING" not in result.output


def test_engage_warns_when_symlinked_workspace_lands_on_another_filesystem(
    tmp_path: Path, monkeypatch,
) -> None:
    import marianne_compiler.agent_cli as cli

    agents, inventory = _installed_agent(tmp_path, "full-lifecycle")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = tmp_path / "link"
    link.symlink_to(elsewhere)
    real_filesystem = cli._filesystem

    def fake(path: Path) -> tuple[int, str]:
        device, mount = real_filesystem(path)
        if elsewhere in (path, *path.parents):
            return device + 1, "/mnt/other"
        return device, mount

    monkeypatch.setattr(cli, "_filesystem", fake)
    base = [
        "engage", "canyon", "--purpose", "job", "--inventory", str(inventory),
        "--agents-dir", str(agents), "--date", "20261020",
        "--evidence-at", "2026-10-20T10:00:00Z",
    ]
    result = runner.invoke(app, [
        *base, "--runs-dir", str(tmp_path / "runs"), "--workspaces-dir", str(link),
    ])
    assert result.exit_code == 0, result.output
    expected = f"workspace: {elsewhere.resolve()}/canyon-job-20261020 (filesystem /mnt/other)"
    assert expected in result.output
    assert "WARNING: workspace" in result.output and "symlink" in result.output
    # The same disk through a symlink is not worth a warning.
    monkeypatch.setattr(cli, "_filesystem", real_filesystem)
    again = runner.invoke(app, [
        *base, "--purpose", "calm", "--runs-dir", str(tmp_path / "runs"),
        "--workspaces-dir", str(link),
    ])
    assert again.exit_code == 0, again.output
    assert "WARNING" not in again.output


def test_attached_task_renders_to_the_copy_and_passes_v004(tmp_path: Path) -> None:
    """The prelude template must resolve through the real runtime renderer."""
    from marianne.core.config import JobConfig
    from marianne.core.sheet import build_sheets
    from marianne.daemon.baton.musician import _resolve_injections
    from marianne.validation.checks.paths import AbsoluteHomePathCheck

    from marianne_compiler.agent_cli import _attach_task

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    source = tmp_path / "my task (v2).md"
    source.write_text("Do the thing.\n")
    bound: dict = {
        "name": "t",
        "workspace": str(run_dir / "ws"),
        "sheet": {"size": 1, "total_items": 1},
        "prompt": {
            "template": "go",
            "variables": {"marianne_agent": {"schema_version": 1}},
        },
    }
    _attach_task(bound, source, run_dir)
    score = run_dir / "t.yaml"
    score.write_text(yaml.safe_dump(bound, sort_keys=False))

    config = JobConfig.from_yaml(score)
    sheet = build_sheets(config)[0]
    context, _skills, _tools = _resolve_injections(
        sheet, sheet.template_variables(total_sheets=1, total_movements=1)
    )
    assert context == ["Do the thing.\n"]
    # The copy lives beside the score, wherever the run directory is.
    moved = tmp_path / "moved"
    run_dir.rename(moved)
    config = JobConfig.from_yaml(moved / "t.yaml")
    sheet = build_sheets(config)[0]
    context, _s, _t = _resolve_injections(
        sheet, sheet.template_variables(total_sheets=1, total_movements=1)
    )
    assert context == ["Do the thing.\n"]
    issues = AbsoluteHomePathCheck().check(
        config, moved / "t.yaml", (moved / "t.yaml").read_text()
    )
    assert issues == []
