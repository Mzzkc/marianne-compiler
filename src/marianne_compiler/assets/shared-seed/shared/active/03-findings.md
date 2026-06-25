# Findings

Use findings for facts another agent can rely on.

## Open Findings

| id | severity | owner | finding | evidence | status |
| --- | --- | --- | --- | --- | --- |
| starter-F-000 | info | unowned | Replace this starter row with the first real finding. | | open |

## Finding Format

| {agent}-F-001 | high | {agent} | State the evidence-backed finding. | `path`, command output, or log line | open |

The format row uses braces as placeholders. Replace them before writing to the
Open Findings table; do not copy placeholder rows as live findings.

Severity values: `critical`, `high`, `medium`, `low`, `info`.
Status values: `open`, `confirmed`, `fixed`, `wontfix`, `superseded`.
Use owner-scoped ids (`{agent}-F-001`, `{agent}-F-002`, ...), not global
incrementing ids.

Every nontrivial claim needs evidence: a path, command output summary, test
name, log line, or exact source.
