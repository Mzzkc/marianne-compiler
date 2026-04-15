"""Composition compiler — turns semantic agent definitions into Mozart scores.

The compiler takes high-level descriptions (agent identities, patterns,
techniques, instrument assignments) and produces complete Mozart score YAML.

Modules:
    identity    — Seed agent identity stores (L1-L4)
    sheets      — Compose sheet structures with parallel phases
    techniques  — Wire technique manifests into cadenza context
    instruments — Resolve per-agent per-sheet instrument assignments
    validations — Generate per-sheet validation rules
    patterns    — Expand named patterns into sheet sequences
    fleet       — Generate fleet configs (concert-of-concerts)
    pipeline    — Top-level compilation pipeline
"""

from __future__ import annotations

from marianne_compiler.fleet import FleetGenerator
from marianne_compiler.identity import IdentitySeeder
from marianne_compiler.instruments import InstrumentResolver
from marianne_compiler.patterns import PatternExpander, PatternStage
from marianne_compiler.pipeline import CompilationPipeline
from marianne_compiler.sheets import SheetComposer
from marianne_compiler.techniques import TechniqueWirer
from marianne_compiler.validations import ValidationGenerator

__all__ = [
    "CompilationPipeline",
    "IdentitySeeder",
    "SheetComposer",
    "TechniqueWirer",
    "InstrumentResolver",
    "ValidationGenerator",
    "PatternExpander",
    "PatternStage",
    "FleetGenerator",
]
