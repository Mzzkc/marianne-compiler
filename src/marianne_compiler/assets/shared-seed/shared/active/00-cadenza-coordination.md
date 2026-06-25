# Cadenza Coordination Contract

This directory is the live shared cadenza for the fleet.

Marianne injects the immediate files in `shared/active/` into configured
agent phases. Directory cadenza loading is not recursive, so anything that
all agents must see now belongs as a direct child of this directory.

Primary communication is stigmergic: agents coordinate by changing durable
artifacts on disk. A2A may be used for live delegation when it is available,
but the durable coordination record must still land here or in the matching
shared directory.

## Required Loop

1. Read every active file before planning.
2. Claim work in `01-task-board.md` before starting overlapping work.
3. Update `02-agent-status.md` when starting, blocking, handing off, or
   completing material work.
4. Use UTC minute timestamps from `date -u +%Y-%m-%dT%H:%MZ` in status rows;
   never append `Z` to local time.
5. Record reusable facts in `03-findings.md`.
6. Record choices that affect other agents in `04-decision-log.md`.
7. Respect `05-directives.md` over self-generated plans.
8. Add handoff pointers to `06-handoff-index.md` when another agent or later
   cycle needs a specific artifact.

## Concurrent Write Safety

The files in this directory are shared by many live agents. If an edit fails
because the file changed since you read it, re-read the latest file and retry
the smallest owner-scoped row change once. Prefer appending your own row to
rewriting shared table sections. If a second conflict blocks the update, write
your detailed artifact under `shared/plans/`, `shared/findings/`,
`shared/decisions/`, or `agents/{name}/cycle-state/`, then record the blocked
update in your own report. Do not spin on the same active file.

## Active File Budget

Keep this folder curated. Move stale detail to `shared/archive/`,
`shared/findings/`, `shared/plans/`, or agent-local cycle state, then leave a
short pointer here.
