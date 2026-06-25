"""Compilation pipeline — top-level orchestrator for the composition compiler.

Takes a semantic config YAML and produces complete Marianne scores for each
agent, plus identity directories, fleet configs, and shared technique modules.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from marianne_compiler.fleet import FleetGenerator
from marianne_compiler.identity import IdentitySeeder
from marianne_compiler.instruments import InstrumentResolver
from marianne_compiler.naming import score_file_stem
from marianne_compiler.patterns import PatternExpander
from marianne_compiler.prompt_template import build_phase_template
from marianne_compiler.sheets import SheetComposer
from marianne_compiler.techniques import TechniqueWirer
from marianne_compiler.validations import ValidationGenerator
from marianne_compiler.workspace_seed import WorkspaceSeeder

_logger = logging.getLogger(__name__)


class CompilationPipeline:
    """Top-level compilation pipeline.

    Coordinates all compiler modules to produce complete Marianne scores
    from a semantic agent configuration.

    Usage::

        pipeline = CompilationPipeline()
        scores = pipeline.compile("config.yaml")
        # Returns: list of score file paths + identity directories created

        # Or programmatically:
        pipeline.compile_agent(agent_def, defaults, output_dir)
        pipeline.seed_identity(agent_def, agents_dir)
    """

    def __init__(
        self,
        *,
        agents_dir: Path | None = None,
        techniques_dir: Path | None = None,
        templates_dir: Path | None = None,
    ) -> None:
        self.identity_seeder = IdentitySeeder(agents_dir)
        self.sheet_composer = SheetComposer(templates_dir)
        self.technique_wirer = TechniqueWirer(techniques_dir)
        self.instrument_resolver = InstrumentResolver()
        self.validation_generator = ValidationGenerator()
        self.pattern_expander = PatternExpander()
        self.fleet_generator = FleetGenerator()
        self.workspace_seeder = WorkspaceSeeder()

    def compile(
        self,
        config_path: str | Path,
        output_dir: str | Path | None = None,
    ) -> list[Path]:
        """Compile a config file into Marianne scores.

        Args:
            config_path: Path to the semantic agent config YAML.
            output_dir: Output directory for generated scores. Defaults
                to ``scores/`` next to the config file.

        Returns:
            List of generated score file paths.
        """
        config_path = Path(config_path)
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}

        if output_dir is None:
            workspace = self._configured_workspace(config, base_dir=config_path.parent)
            output_dir = (
                Path(workspace) / "scores"
                if workspace
                else config_path.parent / "scores"
            )
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        return self.compile_config(config, output_dir, base_dir=config_path.parent)

    def compile_config(
        self,
        config: dict[str, Any],
        output_dir: Path,
        *,
        base_dir: Path | None = None,
    ) -> list[Path]:
        """Compile a config dict into Marianne scores.

        Args:
            config: Parsed compiler config dict.
            output_dir: Directory to write generated scores.

        Returns:
            List of generated score file paths.
        """
        self._configure_from_config(config, base_dir=base_dir)

        agents = config.get("agents", [])
        if not agents:
            raise ValueError("Config must contain at least one agent")

        defaults = config.get("defaults", {})
        workspace = self._configured_workspace(config) or str(output_dir / "workspace")
        if base_dir is not None:
            workspace = self._configured_workspace(config, base_dir=base_dir) or workspace
        self.workspace_seeder.seed(workspace, config)

        migration_memory_dir = self._resolve_optional_path(
            config.get("defaults", {}).get("migration_memory_dir")
            or config.get("migration_memory_dir"),
            base_dir=base_dir,
        )
        migration_meditation_dir = self._resolve_optional_path(
            config.get("defaults", {}).get("migration_meditation_dir")
            or config.get("migration_meditation_dir"),
            base_dir=base_dir,
        )
        instruments_dir = self._resolve_optional_path(
            config.get("defaults", {}).get("instruments_dir")
            or config.get("instruments_dir"),
            base_dir=base_dir,
        )

        score_paths: list[Path] = []

        for agent_def in agents:
            path = self.compile_agent(
                agent_def,
                defaults,
                output_dir,
                workspace=workspace,
                migration_memory_dir=migration_memory_dir,
                migration_meditation_dir=migration_meditation_dir,
                instruments_dir=instruments_dir,
            )
            score_paths.append(path)

        # Generate fleet config if multiple agents
        if len(agents) > 1:
            fleet_path = output_dir / "fleet.yaml"
            self.fleet_generator.write(config, output_dir, fleet_path)
            score_paths.append(fleet_path)
            _logger.info("Fleet config written: %s", fleet_path)

        _logger.info(
            "Compiled %d agent scores to %s", len(agents), output_dir
        )
        return score_paths

    def compile_agent(
        self,
        agent_def: dict[str, Any],
        defaults: dict[str, Any],
        output_dir: Path,
        *,
        workspace: str = "",
        migration_memory_dir: Path | None = None,
        migration_meditation_dir: Path | None = None,
        instruments_dir: Path | None = None,
    ) -> Path:
        """Compile a single agent definition into a Marianne score.

        Args:
            agent_def: Agent definition dict.
            defaults: Global defaults from compiler config.
            output_dir: Directory to write the score.
            workspace: Workspace path for the agent.

        Returns:
            Path to the generated score file.
        """
        name = agent_def["name"]
        agents_dir = self.identity_seeder.agents_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        # 1. Seed identity
        self.identity_seeder.seed(
            agent_def,
            existing_memory_path=self._agent_named_path(
                agent_def, migration_memory_dir, "existing_memory_path"
            ),
            existing_meditation_path=self._agent_named_path(
                agent_def, migration_meditation_dir, "existing_meditation_path"
            ),
        )

        # 2. Compose sheet structure
        sheet_config = self.sheet_composer.compose(
            agent_def, defaults, agents_dir=agents_dir
        )

        # 3. Wire techniques. #213: when techniques are declared, the
        # input config MUST say where the technique docs live — explicit,
        # no implicit discovery (the silent None made every technique
        # injection a no-op). #215: the compiler-internal copy of the
        # technique docs is deleted; plugins/marianne/techniques/ is the
        # canonical store and callers pass it explicitly.
        declared = dict(defaults.get("techniques", {}))
        declared.update(
            agent_def.get("techniques", {})
            if isinstance(agent_def.get("techniques"), dict)
            else {}
        )
        if declared and self.technique_wirer.techniques_dir is None:
            raise ValueError(
                f"Agent '{name}' declares techniques "
                f"({', '.join(sorted(declared))}) but no techniques_dir is "
                "configured. Set `techniques_dir:` in the compiler config "
                "(canonical store: plugins/marianne/techniques/) or pass "
                "techniques_dir= to CompilationPipeline."
            )
        technique_result = self.technique_wirer.wire(
            agent_def, defaults, workspace=workspace
        )

        # Merge technique cadenzas into sheet cadenzas
        for sheet_num, tech_cadenzas in technique_result["cadenzas"].items():
            if sheet_num not in sheet_config.get("cadenzas", {}):
                sheet_config.setdefault("cadenzas", {})[sheet_num] = []
            sheet_config["cadenzas"][sheet_num].extend(tech_cadenzas)

        # 4. Resolve instruments
        instrument_result = self.instrument_resolver.resolve(agent_def, defaults)

        # Merge instrument assignments into sheet config
        if instrument_result.get("per_sheet_instruments"):
            sheet_config["per_sheet_instruments"] = instrument_result["per_sheet_instruments"]
        if instrument_result.get("per_sheet_instrument_config"):
            sheet_config["per_sheet_instrument_config"] = instrument_result[
                "per_sheet_instrument_config"
            ]
        if instrument_result.get("per_sheet_fallbacks"):
            sheet_config["per_sheet_fallbacks"] = instrument_result["per_sheet_fallbacks"]

        # 5. Generate validations
        validations = self.validation_generator.generate(
            agent_def,
            defaults,
            agents_dir=str(agents_dir),
            instruments_dir=str(instruments_dir) if instruments_dir else "",
        )

        # 6. Expand patterns
        pattern_names = agent_def.get("patterns", [])
        if pattern_names:
            self.pattern_expander.expand(pattern_names, agent_def)

        # 7. Build prompt config — embedding the per-phase technique
        # manifests in the 12-phase template (#211/#212).
        prompt_config = self._build_prompt(
            agent_def,
            defaults,
            technique_manifests=technique_result.get("technique_manifests"),
        )

        score_name = score_file_stem(name, defaults)
        score_path = output_dir / f"{score_name}.yaml"

        # 8. Assemble score
        score = self._assemble_score(
            name=score_name,
            workspace=workspace or str(output_dir / "workspace"),
            self_path=score_path,
            sheet_config=sheet_config,
            prompt_config=prompt_config,
            instrument_result=instrument_result,
            validations=validations,
            defaults=defaults,
            techniques=technique_result.get("runtime_techniques"),
            agent_card=technique_result.get("agent_card"),
        )

        # Write score
        with open(score_path, "w") as f:
            yaml.dump(score, f, default_flow_style=False, sort_keys=False, width=120)
        self._validate_generated_hook_targets(score, score_path)

        _logger.info("Score written: %s", score_path)
        return score_path

    def seed_identity(
        self,
        agent_def: dict[str, Any],
        agents_dir: Path | None = None,
    ) -> Path:
        """Seed identity for a single agent.

        Convenience method that delegates to IdentitySeeder.
        """
        seeder = IdentitySeeder(agents_dir) if agents_dir else self.identity_seeder
        return seeder.seed(agent_def)

    def resolve_instruments(
        self,
        agent_def: dict[str, Any],
        defaults: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve instruments for a single agent.

        Convenience method that delegates to InstrumentResolver.
        """
        return self.instrument_resolver.resolve(agent_def, defaults)

    def _build_prompt(
        self,
        agent_def: dict[str, Any],
        defaults: dict[str, Any],
        technique_manifests: dict[int, str] | None = None,
    ) -> dict[str, Any]:
        """Build the prompt configuration for a score.

        #211: emits the spec §3.3 12-phase ``template`` — each phase gets
        its invocation, and ``stakes``/``thinking_method`` (previously
        emitted as dead variables) are referenced by it. #212: the
        per-phase technique manifests are embedded in the matching phase
        branches instead of being silently dropped.
        """
        name = agent_def["name"]
        stakes = agent_def.get("meditation", defaults.get("stakes", ""))
        thinking_method = defaults.get("thinking_method", "")

        prompt: dict[str, Any] = {
            "template": build_phase_template(technique_manifests),
            "variables": {
                "agent_name": name,
                "role": agent_def.get("role", "builder"),
                "focus": agent_def.get("focus", ""),
                "agent_voice": agent_def.get("voice", ""),
                "agent_identity_dir": str(self.identity_seeder.agents_dir / name),
                # Referenced by the template; empty when unset so
                # StrictUndefined rendering never breaks.
                "stakes": stakes or "",
                "thinking_method": thinking_method or "",
            },
        }

        return prompt

    def _assemble_score(
        self,
        *,
        name: str,
        workspace: str,
        self_path: Path,
        sheet_config: dict[str, Any],
        prompt_config: dict[str, Any],
        instrument_result: dict[str, Any],
        validations: list[dict[str, Any]],
        defaults: dict[str, Any],
        techniques: dict[str, Any] | None = None,
        agent_card: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Assemble the complete score dict."""
        concert_config = defaults.get("concert", {})
        max_depth = min(concert_config.get("max_chain_depth", 100), 100)
        pause_before = defaults.get("pause_before_chain", False)

        score: dict[str, Any] = {
            "name": name,
            "workspace": workspace,
            # Post-#347 shape: execution is configured exclusively through
            # the instrument plugin system — an instrument NAME (or
            # score-local alias), never a backend dict (#214).
            "instrument": instrument_result.get("instrument", "claude-code"),
            "instrument_fallbacks": instrument_result.get("instrument_fallbacks", []),
            "sheet": sheet_config,
            "prompt": prompt_config,
            "retry": {
                "max_retries": 3,
                "base_delay_seconds": 30,
                "max_completion_attempts": 3,
                "completion_threshold_percent": 50,
            },
            "rate_limit": {
                "wait_minutes": 60,
                "max_waits": 24,
            },
            "stale_detection": {
                "enabled": True,
                "idle_timeout_seconds": 3600,
            },
            "parallel": {
                "enabled": True,
                "max_concurrent": 3,
            },
            "concert": {
                "enabled": True,
                "max_chain_depth": max_depth,
            },
            "validations": validations,
        }

        if techniques:
            score["techniques"] = techniques
        if agent_card:
            score["agent_card"] = agent_card

        # Score-local instrument aliases (#214): one alias per distinct
        # (instrument, model) entry so deep fallback chains keep their
        # per-entry models instead of collapsing to profile defaults.
        if instrument_result.get("instruments"):
            score["instruments"] = instrument_result["instruments"]

        # Self-chaining via on_success. The compiler spec names this as
        # {self}; materialize it to a daemon-safe path. Prefer {workspace}
        # when the score is workspace-local so generated fleets are movable.
        score_path_str = self._self_chain_job_path(self_path, workspace)
        score["on_success"] = [
            {
                "type": "run_job",
                "job_path": score_path_str,
                "detached": True,
                "fresh": True,
                "pause_before_chain": pause_before,
            }
        ]

        return score

    @staticmethod
    def _configured_workspace(
        config: dict[str, Any],
        *,
        base_dir: Path | None = None,
    ) -> str:
        """Return the configured workspace, accepting both compiler schemas."""
        project = config.get("project", {})
        raw_workspace = None
        if isinstance(project, dict):
            raw_workspace = project.get("workspace")
        raw_workspace = raw_workspace or config.get("workspace")
        if not raw_workspace:
            return ""

        workspace = Path(str(raw_workspace)).expanduser()
        if base_dir is not None and not workspace.is_absolute():
            workspace = (base_dir / workspace).resolve()
        return str(workspace)

    def _configure_from_config(
        self,
        config: dict[str, Any],
        *,
        base_dir: Path | None = None,
    ) -> None:
        """Apply config-level compiler paths to the pipeline."""
        config_tech_dir = config.get("defaults", {}).get("techniques_dir") or config.get(
            "techniques_dir"
        )
        tech_path = self._resolve_optional_path(config_tech_dir, base_dir=base_dir)
        if tech_path:
            self.technique_wirer.techniques_dir = tech_path

    @staticmethod
    def _resolve_optional_path(
        raw_path: Any,
        *,
        base_dir: Path | None = None,
    ) -> Path | None:
        """Resolve an optional config path relative to the config file."""
        if not raw_path:
            return None
        path = Path(str(raw_path)).expanduser()
        if base_dir is not None and not path.is_absolute():
            path = (base_dir / path).resolve()
        return path

    @staticmethod
    def _agent_named_path(
        agent_def: dict[str, Any],
        directory: Path | None,
        override_key: str,
    ) -> Path | None:
        """Return an agent-specific migration file if configured/present."""
        override = agent_def.get(override_key)
        if override:
            return Path(str(override)).expanduser()
        if not directory:
            return None
        name = agent_def.get("name")
        if not name:
            return None
        candidate = directory / f"{name}.md"
        return candidate if candidate.exists() else None

    @staticmethod
    def _self_chain_job_path(score_path: Path, workspace: str) -> str:
        """Format a self-chain job path using {workspace} when possible."""
        resolved_score_path = score_path.resolve()
        if not workspace:
            return str(resolved_score_path)

        workspace_path = Path(workspace).expanduser()
        if not workspace_path.is_absolute():
            workspace_path = workspace_path.resolve()

        try:
            relative_score_path = resolved_score_path.relative_to(
                workspace_path.resolve()
            )
        except ValueError:
            return str(resolved_score_path)

        return f"{{workspace}}/{relative_score_path.as_posix()}"

    def _validate_generated_hook_targets(
        self,
        score: dict[str, Any],
        score_path: Path,
    ) -> None:
        """Preflight generated run_job hooks against daemon path semantics."""
        hooks = score.get("on_success") or []
        if not isinstance(hooks, list):
            raise ValueError(
                f"Generated score '{score_path}' has invalid on_success hooks: "
                "expected a list"
            )

        for index, hook in enumerate(hooks):
            if not isinstance(hook, dict):
                raise ValueError(
                    f"Generated score '{score_path}' has invalid on_success "
                    f"hook #{index}: expected a mapping"
                )
            if hook.get("type") != "run_job":
                continue

            raw_job_path = hook.get("job_path")
            if not isinstance(raw_job_path, str) or not raw_job_path.strip():
                raise ValueError(
                    f"Generated score '{score_path}' run_job hook #{index} "
                    "must define a non-empty job_path"
                )

            expanded = raw_job_path.replace("{self}", str(score_path.resolve()))
            if "{workspace}" in expanded:
                workspace = score.get("workspace")
                if not workspace:
                    raise ValueError(
                        f"Generated score '{score_path}' run_job hook #{index} "
                        "uses {workspace} but the score has no workspace"
                    )
                expanded = expanded.replace("{workspace}", str(workspace))

            if "{" in expanded or "}" in expanded:
                raise ValueError(
                    f"Generated score '{score_path}' run_job hook #{index} "
                    f"contains unresolved template syntax: {raw_job_path}"
                )

            target = Path(expanded).expanduser()
            if not target.is_absolute():
                raise ValueError(
                    f"Generated score '{score_path}' run_job hook #{index} "
                    f"must resolve to an absolute path: {raw_job_path}"
                )

            if not target.exists():
                raise ValueError(
                    f"Generated score '{score_path}' run_job hook #{index} "
                    f"points to missing score: {target}"
                )
