"""Regression tests for the 2026-04-19 capability-audit defects (#211–#215).

#211 prompt.template emitted (12-phase, references stakes/thinking_method)
#212 technique manifests embedded in the template, not dropped
#213 techniques_dir required when techniques are declared (loud error)
#214 alias-based chains preserve declared depth + per-entry models;
     post-#347 score shape (instrument name, no backend dict)
#215 single technique-doc store (compiler-internal copy deleted)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from marianne_compiler.instruments import InstrumentResolver
from marianne_compiler.pipeline import CompilationPipeline
from marianne_compiler.prompt_template import build_phase_template
from marianne_compiler.sheets import SHEETS_PER_CYCLE
from marianne_compiler.validations import ValidationGenerator


def _defaults_with_chain() -> dict[str, object]:
    """The #214 reproducer shape: a 7-entry chain with per-model entries."""
    chain = [
        {"instrument": "openrouter", "model": "zhipu/glm-4.5-air"},
        {"instrument": "openrouter", "model": "google/gemma-4"},
        {"instrument": "openrouter", "model": "nvidia/nemotron-3"},
        {"instrument": "openrouter", "model": "zhipu/glm-4.5"},
        {"instrument": "gemini-cli"},
        {"instrument": "opencode"},
        {"instrument": "claude-code", "model": "claude-sonnet-4-5"},
    ]
    return {
        "instruments": {
            "work": {
                "primary": {"instrument": "openrouter", "model": "minimax/minimax-2.5"},
                "fallbacks": chain,
            },
        },
    }


class TestAliasChains214:
    def test_declared_chain_depth_preserved(self) -> None:
        """Four openrouter entries with different models stay FOUR entries."""
        result = InstrumentResolver().resolve(
            {"name": "a", "voice": "v", "focus": "f"}, _defaults_with_chain()
        )
        chain = result["per_sheet_fallbacks"][3]  # work sheet
        assert len(chain) >= 7
        openrouter_aliases = [a for a in chain if a.startswith("openrouter--")]
        assert len(openrouter_aliases) == 4  # not collapsed to one name

    def test_aliases_carry_models(self) -> None:
        result = InstrumentResolver().resolve(
            {"name": "a", "voice": "v", "focus": "f"}, _defaults_with_chain()
        )
        aliases = result["instruments"]
        assert aliases["openrouter--gemma-4"]["config"]["model"] == "google/gemma-4"
        assert aliases["openrouter--gemma-4"]["profile"] == "openrouter"

    def test_no_backend_dict_anywhere(self) -> None:
        """Post-#347: instrument name, never a type+model backend dict."""
        result = InstrumentResolver().resolve(
            {"name": "a", "voice": "v", "focus": "f"}, _defaults_with_chain()
        )
        assert "backend" not in result
        assert isinstance(result["instrument"], str)


class TestTemplate211:
    def test_all_twelve_phases_present(self) -> None:
        template = build_phase_template()
        for sheet_num in range(1, SHEETS_PER_CYCLE + 1):
            marker = "if" if sheet_num == 1 else "elif"
            assert f"{{% {marker} stage == {sheet_num} %}}" in template
        assert template.rstrip().endswith("{% endif %}")

    def test_stakes_and_thinking_method_referenced(self) -> None:
        template = build_phase_template()
        assert "{{ stakes }}" in template
        assert "{{ thinking_method }}" in template

    def test_pipeline_emits_template(self, tmp_path: Path) -> None:
        pipeline = CompilationPipeline(agents_dir=tmp_path / "agents")
        prompt = pipeline._build_prompt(
            {"name": "a", "role": "builder", "meditation": "the stakes"},
            {"thinking_method": "TSVS"},
        )
        assert "template" in prompt
        assert "{% if stage == 1 %}" in prompt["template"]
        # Previously-dead values are now template-referenced variables.
        assert prompt["variables"]["stakes"] == "the stakes"
        assert prompt["variables"]["thinking_method"] == "TSVS"

    def test_phase_output_section_labels_match_content_validations(self) -> None:
        """Generated instructions must name the exact section labels validators require."""
        template = build_phase_template()
        validations = ValidationGenerator().generate(
            {"name": "a", "voice": "v", "focus": "f"},
            {},
        )

        for rule in validations:
            if rule.get("type") != "content_contains":
                continue
            condition = str(rule["condition"])
            assert condition.startswith("stage == ")
            stage = int(condition.removeprefix("stage == "))
            branch = self._template_branch(template, stage)
            assert rule["pattern"] in branch

    @staticmethod
    def _template_branch(template: str, stage: int) -> str:
        keyword = "if" if stage == 1 else "elif"
        start_marker = f"{{% {keyword} stage == {stage} %}}"
        start = template.index(start_marker)
        next_markers = [
            marker
            for marker in (
                template.find("{% elif stage ==", start + len(start_marker)),
                template.find("{% endif %}", start + len(start_marker)),
            )
            if marker != -1
        ]
        end = min(next_markers)
        return template[start:end]


class TestManifests212:
    def test_manifests_embedded_in_matching_phase(self) -> None:
        manifests = {3: "## Techniques live this phase\n- github (mcp)"}
        template = build_phase_template(manifests)
        work_branch = template.split("{% elif stage == 3 %}")[1].split("{% elif")[0]
        assert "github (mcp)" in work_branch
        recon_branch = template.split("{% elif stage == 2 %}")[0]
        assert "github (mcp)" not in recon_branch


class TestTechniquesDir213:
    def test_declared_techniques_without_dir_fail_loudly(
        self, tmp_path: Path
    ) -> None:
        pipeline = CompilationPipeline(agents_dir=tmp_path / "agents")
        with pytest.raises(ValueError, match="techniques_dir"):
            pipeline.compile_agent(
                {
                    "name": "a",
                    "voice": "v",
                    "focus": "f",
                    "techniques": {"memory-protocol": {"kind": "skill", "phases": ["all"]}},
                },
                {},
                tmp_path / "out",
            )

    def test_no_techniques_compiles_without_dir(self, tmp_path: Path) -> None:
        pipeline = CompilationPipeline(agents_dir=tmp_path / "agents")
        score_path = pipeline.compile_agent(
            {"name": "a", "voice": "v", "focus": "f"}, {}, tmp_path / "out"
        )
        assert score_path.exists()


class TestSingleStore215:
    def test_compiler_internal_copy_deleted(self) -> None:
        import marianne_compiler

        pkg_dir = Path(marianne_compiler.__file__).parent
        assert not (pkg_dir / "technique_modules").exists()
