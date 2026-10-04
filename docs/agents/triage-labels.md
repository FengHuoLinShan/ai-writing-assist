# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | —                    | Maintainer needs to evaluate this issue  |
| `needs-info`               | —                    | Waiting on reporter for more information |
| `ready-for-agent`          | —                    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | —                    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Aside from `wontfix`, the role labels above are not configured in this repo's tracker (verified via `gh label list`, 2026-09-30). The actual label set is: `bug`, `documentation`, `duplicate`, `enhancement`, `help wanted`, `good first issue`, `invalid`, `question`, `wontfix`, `dependencies`, `javascript`, `docker`, `docker_compose`, `github_actions`, `python:uv`. Adopting a role label marked "—" requires creating it first with `gh label create` (including `needs-triage`); label creation is a GitHub metadata operation and is not performed as part of a docs-only reorganization.
