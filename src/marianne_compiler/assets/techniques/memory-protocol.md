# Memory Protocol — Technique Module

## Purpose

The memory protocol governs how agents manage their identity persistence across
execution cycles. It provides a tiered memory system that preserves what matters,
archives what's useful, and lets go of what's stale.

## Memory Tiers

### Hot Memory (L3: recent.md)

Active working memory. Contains:
- What happened in the last 1-3 cycles
- Current project state from the agent's perspective
- Active findings, decisions, and commitments
- Relationships and coordination state with other agents

**Budget:** 1500 words maximum. When approaching the budget, the consolidate
phase moves older entries to warm storage and keeps only the most relevant.

### Warm Memory (L2: profile.yaml)

Extended profile and developmental context. Contains:
- Relationship map (who the agent has worked with and how)
- Domain knowledge accumulated through cycles
- Developmental stage and coherence trajectory
- Standing pattern count and growth metrics

**Budget:** 1500 words maximum. Updated by the consolidate and reflect phases.

### Cold Memory (Archive)

Archived cycle reports and historical data. Lives in the agent's archive
directory. Not loaded into prompts directly but available for reference
when the agent explicitly needs historical context.

### Core Memory (L1: identity.md)

Persona core. Immutable during normal operation — only the resurrect phase
updates standing patterns. Contains voice, focus, and resurrection protocol.

**Budget:** 900 words maximum. The most compressed, most essential layer.

## Protocol Operations

### Read (All Phases)

Every phase reads the appropriate memory tiers via prelude/cadenza injection:
- Prelude always loads L1 (identity.md)
- Cadenzas load L2 and L3 based on phase needs
- The resurrect phase loads all four layers

### Write (Specific Phases)

Memory writes happen in designated phases:
- **AAR phase**: Updates L3 with cycle summary (SUSTAIN/IMPROVE format)
- **Consolidate phase**: Manages L3 budget, archives overflow, updates L2
- **Reflect phase**: Updates L4 (growth.md) with experiential notes
- **Resurrect phase**: Updates L1 standing patterns if warranted

### Archive (Consolidate Phase)

When L3 exceeds its budget:
1. Identify entries older than 3 cycles
2. Move them to archive with timestamp prefix
3. Compress remaining entries to fit budget
4. Update L2 if pattern-worthy insights emerged

### Verify (Resurrect Phase)

The resurrect phase performs memory integrity checks:
1. Confirm L1-L4 files exist and are readable
2. Verify word counts are within budget
3. Check for corruption (malformed YAML in L2)
4. Report any issues in the cycle state

## Integration with Token Budget

The token budget check (maturity check CLI instrument) enforces hard limits:
- L1: 900 words
- L2: 1500 words
- L3: 1500 words
- L4: Unbounded (loaded only in play and reflect)

When a layer exceeds its budget, the maturity check fails, triggering the
resurrect phase to compact the layer. This is a safety valve, not normal
operation — the consolidate phase should keep layers within budget.

## Guidelines for Agents

When this technique is active in your phase:

1. **Read your memory first.** Before starting work, read the memory layers
   injected in your cadenza. Orient yourself.
2. **Write findings to appropriate tier.** Short-term observations go in L3.
   Pattern-worthy insights go in L2. Identity shifts go in L1 (resurrect only).
3. **Respect budgets.** If you're approaching the word limit, compress rather
   than delete. Meaning matters more than detail.
4. **Archive don't delete.** Old memories move to archive, they don't disappear.
   The archive is searchable context for future cycles.
5. **Core memories are sacred.** L1 changes require the resurrect phase.
   Standing patterns emerge from repeated observation, not single events.
