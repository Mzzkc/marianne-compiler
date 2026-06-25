# Agent Status

Update this when your work state changes. Keep entries compact.
The `updated` column must be UTC minute time from `date -u +%Y-%m-%dT%H:%MZ`;
do not append `Z` to local time.

## Current Status

| agent | phase | state | current work | next handoff | updated |
| --- | --- | --- | --- | --- | --- |
| example | recon | available | Replace this starter row on first use. | | |

## Entry Example

| forge | work | claimed | Implement workspace seeder. | sentinel inspect after tests pass. | 2026-06-21T10:30Z |

State values: `available`, `claimed`, `blocked`, `handoff`, `reviewing`,
`complete`.

If blocked, include the blocking file, command, error, or missing decision.

## Concurrent Write Safety

If this file changes between read and edit, re-read it and retry only your
agent row once. If it changes again, write the status evidence in your required
cycle-state artifact and continue; do not stall the sheet by repeatedly editing
this shared table.
