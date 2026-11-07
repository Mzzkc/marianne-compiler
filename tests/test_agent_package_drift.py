"""Compiler changes must update the portable package shipped to users."""

from pathlib import Path

import pytest
import yaml

from marianne_compiler.agent_package import generate_agent_package


@pytest.mark.timeout(180)
def test_checked_in_package_matches_regeneration(tmp_path: Path) -> None:
    compiler = Path(__file__).resolve().parents[1]
    plugins = compiler.parent / "plugins" / "marianne"
    checked_in = plugins / "agent-scores"
    if not checked_in.is_dir():
        pytest.skip("portable plugin package is absent in compiler-only checkouts")

    config_path = compiler / "src/marianne_compiler/assets/generic-fleet.yaml"
    config = yaml.safe_load(config_path.read_text())
    generated = tmp_path / "agent-scores"
    generate_agent_package(config, generated, techniques_dir=plugins / "techniques")

    def files(root: Path) -> dict[Path, bytes]:
        return {
            path.relative_to(root): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file() and path.relative_to(root) != Path("README.md")
        }

    actual = files(checked_in)
    expected = files(generated)
    missing = sorted(expected.keys() - actual.keys())
    extra = sorted(actual.keys() - expected.keys())
    changed = sorted(
        path for path in actual.keys() & expected.keys() if actual[path] != expected[path]
    )
    assert not (missing or extra or changed), (
        "Packaged agents drifted from the compiler; from compiler/ run "
        "uv run marianne-agents package src/marianne_compiler/assets/generic-fleet.yaml "
        "--output ../plugins/marianne/agent-scores "
        "--techniques-dir ../plugins/marianne/techniques\n"
        f"Missing ({len(missing)}): {missing[:10]}\n"
        f"Extra ({len(extra)}): {extra[:10]}\n"
        f"Changed ({len(changed)}): {changed[:10]}"
    )
