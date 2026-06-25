# Task Board

Use this file for current-cycle claims only. Do not use it as a full backlog.

## Active

| id | owner | status | task | evidence |
| --- | --- | --- | --- | --- |
| starter-T-000 | unowned | ready | Replace this starter row with the first real fleet task. | |

## Claim Format

When claiming work, add or update one row:

| {agent}-T-001 | {agent} | claimed | Describe the current-cycle task. | `cycle-state/{agent}-plan.md` |

The format row uses braces as placeholders. Replace them before writing to the
Active table; do not copy placeholder rows as live claims.

Status values: `ready`, `claimed`, `blocked`, `review`, `done`, `deferred`.
Use owner-scoped ids (`{agent}-T-001`, `{agent}-T-002`, ...), not global
incrementing ids. Parallel agents cannot safely reserve global numbers.

## Collision Rule

If another agent already owns overlapping work, add a note to that row instead
of starting a competing implementation.

## Concurrent Write Safety

If this file changes between read and edit, re-read it and retry only your
owner-scoped row once. If it changes again, put the detailed task note in your
cycle-state report and mark the coordination update as blocked there instead of
looping on this shared table.
