# Mateship Protocol — Technique Module

## Purpose

The mateship protocol governs how agents collaborate through shared findings.
It provides a structured pipeline for discovering, proving, fixing, and
verifying issues across the agent fleet. No agent works alone — what one
agent finds, another can pick up, and the fleet converges on solutions.

## The Finding Pipeline

### 1. Filed (Discovery)

Any agent can file a finding during any phase. Findings are markdown files
in the shared findings directory:

```
shared/findings/{severity}-{agent}-{short-description}.md
```

Severity levels:
- **P0**: Critical — blocks progress, requires immediate attention
- **P1**: Important — should be addressed this cycle
- **P2**: Notable — worth tracking, can wait

A finding file contains:
- **What**: Description of the issue
- **Where**: File paths, function names, line numbers
- **Why it matters**: Impact assessment
- **Who found it**: Agent name and cycle number
- **Status**: filed | claimed | proved | fixed | verified

### 2. Claimed (Ownership)

An agent claims a finding by updating its status to "claimed" and adding
their name. Claim-before-work prevents collision — if a finding is already
claimed, another agent should not duplicate the work.

```markdown
Status: claimed
Claimed by: agent-b (cycle 12)
```

### 3. Proved (Validation)

The claiming agent proves the finding — reproduces the issue, writes a
failing test, or demonstrates the impact. A proved finding has evidence,
not just a report.

```markdown
Status: proved
Evidence: tests/test_boundary.py::test_leaking_import — FAILS as expected
```

### 4. Fixed (Resolution)

The fix is implemented. The finding file is updated with what was done:

```markdown
Status: fixed
Fix: Moved import behind TYPE_CHECKING guard in core/config.py:15
Commit: abc1234
```

### 5. Verified (Confirmation)

A different agent verifies the fix. This is critical — the fixer is not
the verifier. The inspect phase is the natural home for verification.

```markdown
Status: verified
Verified by: agent-c (cycle 13)
Tests: All passing. Import boundary intact.
```

## Shared Directory Structure

```
shared/
  findings/
    P0-agent-a-import-boundary-leak.md
    P1-agent-b-missing-validation.md
    P2-agent-c-unused-import.md
```

Agents read the findings directory during recon to understand the current
state of shared work. The coordination technique teaches agents how to
manage this space.

## Protocol Rules

1. **File findings immediately.** Don't wait for the AAR phase. If you
   find something during work, file it now.
2. **Claim before working.** Check if someone else has already claimed
   the finding. Don't duplicate effort.
3. **Prove before fixing.** A finding without evidence is a guess. Write
   a test or demonstrate the issue before implementing a fix.
4. **Verify across agents.** The fixer doesn't verify their own fix. Let
   another agent confirm. Cross-verification catches blind spots.
5. **Update status promptly.** Stale finding files mislead other agents.
   Keep status current.
6. **Severity is honest.** P0 means "blocks progress." Don't inflate
   severity for attention. Don't deflate it to avoid urgency.

## Integration with Agent Phases

- **Recon**: Read findings directory. Understand what's been found, claimed, fixed.
- **Plan**: Plan work that addresses unclaimed P0/P1 findings.
- **Work**: File new findings. Claim and fix existing ones.
- **Inspect**: Verify fixes. File new findings from quality review.
- **AAR**: Summarize finding pipeline status. What's open? What was fixed?

## Guidelines for Agents

When this technique is active in your phase:

1. **Check shared/findings/ first.** Before starting your own investigation,
   see what others have already found.
2. **File findings in the correct format.** Use the severity-agent-description
   naming convention. Include all required fields.
3. **Claim explicitly.** Write your name and cycle number. Other agents respect
   claims.
4. **Provide evidence.** "I think there's a bug" is not a finding. "This test
   fails because of X" is a finding.
5. **Verify others' work.** If you see a "fixed" finding in your domain, run
   the verification. Trust but verify.
6. **Respect the pipeline.** Filed -> Claimed -> Proved -> Fixed -> Verified.
   Don't skip steps.
