# Directives

Composer or conductor directives go here. These override ordinary agent plans.

## Active Directives

| id | source | directive | scope | status |
| --- | --- | --- | --- | --- |
| starter-DIR-000 | starter | Replace this starter row with real active directives. | fleet | inactive |

## Directive Format

| {source}-DIR-001 | {source} | State the directive. | affected scope | active |

Status values: `active`, `fulfilled`, `superseded`, `inactive`.
Use source-scoped ids (`{source}-DIR-001`, `{agent}-DIR-001`, ...), not
global incrementing ids.

The format row uses braces as placeholders. Replace them before writing to the
Active Directives table; do not copy placeholder rows as live directives.

Agents must read active directives during recon and plan. If a directive
conflicts with an agent's task, the agent records the conflict in the task
board before proceeding.
