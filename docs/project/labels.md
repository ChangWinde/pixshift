# Label Strategy

The labels that exist on the repository today, and when to apply them. This
document describes reality, not an aspiration: applying a label that is not
listed here fails, because GitHub rejects unknown labels on `gh issue create`
and `gh pr edit`.

## Area labels — which part of the system changed

| Label | Scope |
| --- | --- |
| `area:cli` | Command surface: options, output rendering, exit codes |
| `area:core` | Shared policy: paths, atomic writes, metadata, parallel execution |
| `area:ops` | Operation wrappers between commands and engines |
| `area:pdf` | PDF engine and the `pdf` command group |
| `area:docs` | Documentation, including the site |
| `area:ci` | Workflows, tooling, release automation |
| `area:examples` | Scripts under `examples/` |

Apply as many as genuinely apply; most changes need one or two. `pr-labeler.yml`
adds area labels automatically from changed paths, so a pull request usually
needs no manual area label.

## Type labels — what kind of change it is

| Label | Use for |
| --- | --- |
| `enhancement` | New capability or a meaningful improvement to an existing one |
| `bug` | Incorrect behaviour against a documented or reasonable expectation |
| `documentation` | Documentation-only change |
| `type:docs` | Legacy alias of `documentation`, kept for existing issues |
| `type:test` | Test or verification-harness work with no behaviour change |
| `question` | Usage question rather than a defect |

## Housekeeping labels

`duplicate`, `invalid`, `wontfix`, `good first issue`, `help wanted`, plus
`dependencies`, `github_actions` and `python:uv`, which Dependabot applies on
its own pull requests.

## Deliberately absent

There is no priority, status, or breaking-risk taxonomy. On a repository this
size those fields duplicate information that issue state, milestones and the
pull request itself already carry, and stale status labels are worse than no
status labels. Severity and risk belong in the issue body, where they can be
justified.

## Adding a label

Creating labels requires repository admin rights (`gh label create`). Add one
only when it changes how work is found or filtered, and update this table in
the same pull request — a label that exists but is undocumented gets used
inconsistently within weeks.
