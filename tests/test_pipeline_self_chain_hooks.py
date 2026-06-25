"""Regression tests for generated self-chain hook paths."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from marianne_compiler.pipeline import CompilationPipeline


def _agent(name: str) -> dict[str, str]:
    return {
        "name": name,
        "voice": f"{name} voice",
        "focus": f"{name} focus",
    }


def test_compile_agent_emits_absolute_existing_self_chain_path(
    tmp_path: Path,
) -> None:
    pipeline = CompilationPipeline(agents_dir=tmp_path / "agents")
    score_path = pipeline.compile_agent(
        _agent("canyon"),
        {},
        tmp_path / "scores",
        workspace=str(tmp_path / "workspace"),
    )

    score = yaml.safe_load(score_path.read_text())
    hook = score["on_success"][0]

    assert hook["type"] == "run_job"
    assert hook["job_path"] == str(score_path.resolve())
    assert Path(hook["job_path"]).is_absolute()
    assert Path(hook["job_path"]).exists()
    assert "{" not in hook["job_path"]
    assert "}" not in hook["job_path"]
    assert hook["fresh"] is True
    assert hook["detached"] is True


def test_compile_agent_emits_workspace_relative_self_chain_when_score_is_local(
    tmp_path: Path,
) -> None:
    pipeline = CompilationPipeline(agents_dir=tmp_path / "agents")
    workspace = tmp_path / "workspace"
    output_dir = workspace / "scores"

    score_path = pipeline.compile_agent(
        _agent("canyon"),
        {},
        output_dir,
        workspace=str(workspace),
    )

    score = yaml.safe_load(score_path.read_text())
    hook = score["on_success"][0]

    assert hook["job_path"] == "{workspace}/scores/canyon.yaml"
    pipeline._validate_generated_hook_targets(score, score_path)


def test_compile_config_reads_top_level_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    output_dir = workspace / "scores"
    pipeline = CompilationPipeline(agents_dir=tmp_path / "agents")

    paths = pipeline.compile_config(
        {
            "name": "fleet",
            "workspace": str(workspace),
            "agents": [_agent("canyon")],
        },
        output_dir,
    )

    score_path = paths[0]
    score = yaml.safe_load(score_path.read_text())
    assert score["workspace"] == str(workspace)
    assert score["on_success"][0]["job_path"] == "{workspace}/scores/canyon.yaml"


def test_compile_config_namespaces_score_files_without_renaming_agent_identity(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    output_dir = workspace / "scores"
    pipeline = CompilationPipeline(agents_dir=tmp_path / "agents")

    paths = pipeline.compile_config(
        {
            "project": {"name": "fleet", "workspace": str(workspace)},
            "defaults": {"job_name_prefix": "bc9k-"},
            "agents": [_agent("canyon"), _agent("forge")],
        },
        output_dir,
    )

    score_paths = [path for path in paths if path.name != "fleet.yaml"]
    assert {path.name for path in score_paths} == {
        "bc9k-canyon.yaml",
        "bc9k-forge.yaml",
    }

    canyon = yaml.safe_load((output_dir / "bc9k-canyon.yaml").read_text())
    assert canyon["name"] == "bc9k-canyon"
    assert canyon["prompt"]["variables"]["agent_name"] == "canyon"
    assert canyon["prompt"]["variables"]["agent_identity_dir"].endswith("/canyon")
    assert canyon["on_success"][0]["job_path"] == "{workspace}/scores/bc9k-canyon.yaml"

    fleet = yaml.safe_load((output_dir / "fleet.yaml").read_text())
    assert fleet["name"] == "bc9k-fleet-fleet"
    assert {
        Path(score["path"]).name
        for score in fleet["scores"]
    } == {"bc9k-canyon.yaml", "bc9k-forge.yaml"}


def test_compile_config_validates_each_generated_agent_hook(
    tmp_path: Path,
) -> None:
    pipeline = CompilationPipeline(agents_dir=tmp_path / "agents")
    output_dir = tmp_path / "scores"

    paths = pipeline.compile_config(
        {
            "project": {"name": "fleet", "workspace": str(tmp_path / "workspace")},
            "agents": [_agent("canyon"), _agent("forge"), _agent("axiom")],
        },
        output_dir,
    )

    score_paths = [path for path in paths if path.name != "fleet.yaml"]
    assert {path.name for path in score_paths} == {
        "canyon.yaml",
        "forge.yaml",
        "axiom.yaml",
    }

    for score_path in score_paths:
        score = yaml.safe_load(score_path.read_text())
        hook = score["on_success"][0]
        assert hook["job_path"] == str(score_path.resolve())
        assert Path(hook["job_path"]).exists()


def test_generated_hook_validation_accepts_spec_self_placeholder(
    tmp_path: Path,
) -> None:
    pipeline = CompilationPipeline(agents_dir=tmp_path / "agents")
    score_path = tmp_path / "scores" / "canyon.yaml"
    score_path.parent.mkdir(parents=True)
    score_path.write_text("name: canyon\n")

    pipeline._validate_generated_hook_targets(
        {
            "name": "canyon",
            "workspace": str(tmp_path / "workspace"),
            "on_success": [{"type": "run_job", "job_path": "{self}"}],
        },
        score_path,
    )


def test_generated_hook_validation_rejects_old_workspace_template(
    tmp_path: Path,
) -> None:
    pipeline = CompilationPipeline(agents_dir=tmp_path / "agents")
    score_path = tmp_path / "scores" / "canyon.yaml"

    with pytest.raises(ValueError, match="unresolved template"):
        pipeline._validate_generated_hook_targets(
            {
                "name": "canyon",
                "workspace": str(tmp_path / "workspace"),
                "on_success": [
                    {
                        "type": "run_job",
                        "job_path": "{{workspace}}/../canyon.yaml",
                    }
                ],
            },
            score_path,
        )


def test_generated_hook_validation_rejects_missing_score_target(
    tmp_path: Path,
) -> None:
    pipeline = CompilationPipeline(agents_dir=tmp_path / "agents")
    score_path = tmp_path / "scores" / "canyon.yaml"
    missing_path = tmp_path / "scores" / "missing.yaml"

    with pytest.raises(ValueError, match="missing score"):
        pipeline._validate_generated_hook_targets(
            {
                "name": "canyon",
                "workspace": str(tmp_path / "workspace"),
                "on_success": [
                    {"type": "run_job", "job_path": str(missing_path.resolve())}
                ],
            },
            score_path,
        )


def test_generated_hook_validation_rejects_relative_target(
    tmp_path: Path,
) -> None:
    pipeline = CompilationPipeline(agents_dir=tmp_path / "agents")

    with pytest.raises(ValueError, match="absolute path"):
        pipeline._validate_generated_hook_targets(
            {
                "name": "canyon",
                "workspace": str(tmp_path / "workspace"),
                "on_success": [{"type": "run_job", "job_path": "canyon.yaml"}],
            },
            tmp_path / "scores" / "canyon.yaml",
        )
