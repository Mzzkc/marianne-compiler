# Marianne Compiler

Composition compiler for [Marianne AI Compose](https://github.com/Mzzkc/marianne-ai-compose) — takes semantic agent definitions and produces executable Mozart score YAML.

## What It Does

**Input:** Semantic YAML describing agents as people — voice, focus, meditation, techniques, instruments.

**Output:** Mozart score YAML (one per agent), identity directories (`~/.mzt/agents/`), fleet configs, agent card sidecars.

The compiler is a deterministic expansion engine. Same input produces same output. No AI reasoning at compile time.

## Modules

- **pipeline** — Top-level orchestrator
- **identity** — L1-L4 identity stack seeder
- **sheets** — 12-sheet agent lifecycle composer
- **techniques** — Cadenza injection, MCP config, A2A cards
- **instruments** — Per-sheet assignment with fallback chains
- **validations** — Per-phase conditional validations
- **patterns** — Rosetta corpus expansion
- **fleet** — Concert-of-concerts from roster

## Relationship to Marianne

The compiler produces YAML that Marianne runs. The score YAML format is the interface. The compiler depends on Marianne's runtime infrastructure (technique system, MCP pool, A2A, code mode) but does not import Marianne code.

## Relationship to bc9k

[CIAB](https://github.com/Mzzkc/backyard-capitalism-9000) wraps this compiler with its roster system, org builder, and governance layer. bc9k is a product built on this compiler.
