# Handoff Index

Use this file to point other agents to detailed artifacts outside the active
cadenza folder.

## Handoffs

| id | from | to | artifact | reason | status |
| --- | --- | --- | --- | --- | --- |
| starter-H-000 | starter | next-agent | Replace this starter row with real handoffs. | | inactive |

## Handoff Format

| {agent}-H-001 | {agent} | target-agent | `shared/plans/artifact.md` | Why the handoff is ready. | ready |

The format row uses braces as placeholders. Replace them before writing to the
Handoffs table; do not copy placeholder rows as live handoffs.

Status values: `ready`, `accepted`, `blocked`, `done`, `inactive`.
Use owner-scoped ids (`{agent}-H-001`, `{agent}-H-002`, ...), not global
incrementing ids.

Detailed reports should live in `shared/plans/`, `shared/findings/`,
`shared/decisions/`, or `agents/{name}/cycle-state/`. Keep only pointers here.
