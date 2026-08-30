"""Composition compiler — turns semantic agent definitions into Marianne scores.

The compiler takes high-level descriptions (agent identities, patterns,
techniques, instrument assignments) and produces complete Marianne score YAML.

Modules:
    identity    — Initialize and reconcile agent identity stores (L1-L4)
    capabilities — Bind semantic phase requirements to live instrument evidence
    agent_package — Generate portable seeds and engagement score sets
    memory_census — Find canonical, snapshot, and unknown memory trees read-only
    sheets      — Compose sheet structures with parallel phases
    techniques  — Wire technique manifests into cadenza context
    instruments — Resolve per-agent per-sheet instrument assignments
    validations — Generate per-sheet validation rules
    patterns    — Expand named patterns into sheet sequences
    fleet       — Generate fleet configs (concert-of-concerts)
    pipeline    — Top-level compilation pipeline
"""

from __future__ import annotations

from marianne_compiler.agent_package import generate_agent_package, install_agent_package
from marianne_compiler.capabilities import bind_config_to_capabilities, resolve_phase_routes
from marianne_compiler.fleet import FleetGenerator
from marianne_compiler.identity import IdentitySeeder, ReconcileResult
from marianne_compiler.instruments import InstrumentResolver
from marianne_compiler.memory_census import census_agent_memory
from marianne_compiler.patterns import PatternExpander, PatternStage
from marianne_compiler.pipeline import CompilationPipeline
from marianne_compiler.sheets import SheetComposer
from marianne_compiler.techniques import TechniqueWirer
from marianne_compiler.validations import ValidationGenerator

__all__ = [
    "CompilationPipeline",
    "IdentitySeeder",
    "ReconcileResult",
    "bind_config_to_capabilities",
    "resolve_phase_routes",
    "generate_agent_package",
    "install_agent_package",
    "census_agent_memory",
    "SheetComposer",
    "TechniqueWirer",
    "InstrumentResolver",
    "ValidationGenerator",
    "PatternExpander",
    "PatternStage",
    "FleetGenerator",
]
