# Contributing to PixShift

Thanks for your interest in improving PixShift.

## Development Setup

```bash
uv sync --frozen --extra dev
uv run pytest -q
```

Quality gates (same as CI):

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy . --ignore-missing-imports
uv run pytest -q --cov=pixshift --cov-fail-under=78
```

Optional pre-commit hooks:

```bash
uv run pre-commit install
```

Large-scale verification (before releases or contract changes):

```bash
# End-to-end sweep: seeded corpus + every CLI surface + schema validation
uv run python scripts/e2e_sweep.py --images 400 --seed 1

# Randomized property fuzzing (the default profile is deterministic)
PIXSHIFT_HYPOTHESIS_PROFILE=stress uv run pytest tests/automation/test_property_contracts.py
```

## Project Expectations

- Keep changes focused and minimal.
- Prefer typed functions and concise English comments.
- Maintain CLI UX consistency across commands.
- Add or update tests for behavior changes.
- Update docs when command behavior changes.

## Documentation

Every document has one audience and one home. Writing user-facing prose into an
engineering reference (or the reverse) is the fastest way to make both rot.

| Audience | Where | Language |
| --- | --- | --- |
| Users of the CLI | `docs/index.md`, `docs/install.md`, `docs/images.md`, `docs/pdf.md`, `docs/video.md`, `docs/automation.md`, `docs/JSON_OUTPUT.md`, `docs/faq.md` — published as the site | Chinese, matching the CLI's own output |
| Contributors | `README.md`, `.github/CONTRIBUTING.md`, `docs/project/architecture.md`, `docs/project/releasing.md`, `docs/project/labels.md` | English |
| Agents | `AGENTS.md`, `docs/schemas/v1/` | English |
| The record | `CHANGELOG.md`, `docs/adr/`, `docs/project/goals.md`, `docs/project/performance.md` | English |

Rules that keep the set coherent:

- **A behaviour change updates its documentation in the same pull request.** A
  new command or option is not done until the relevant manual chapter shows it.
- **Write option tables from the command's actual `--help` output**, not from
  the previous version of the docs.
- **Numbers must be reproducible.** Performance claims cite a benchmark that
  someone else can run; coverage and gate figures must match CI.
- **Architecture decision records are immutable history.** Supersede an ADR with
  a new one; do not rewrite an accepted one.
- **New pages under `docs/` must be either published or excluded.** Add them to
  the site nav in `mkdocs.yml`, or to `exclude_docs` if they are engineering
  references.

The full placement, ownership, change-impact, retirement, and publication policy
lives in `docs/project/documentation-governance.md`.

`tests/repository/test_docs_governance.py` enforces the machine-checkable half of this:
every catalogued command appears in the manual, the manual invents no command
that does not exist, coverage gates and `schema_version` agree across code, CI
and prose, relative links and referenced repository paths resolve, and no page
is silently orphaned. Prose quality still needs a human reviewer.

Run both documentation gates after changing any Markdown, schema, navigation, or
repository metadata:

```bash
uv run pytest -q tests/repository/test_docs_governance.py
uv run mkdocs build --strict
```

## Pull Request Process

1. Open an issue first for major changes.
2. Create a focused PR with clear scope.
3. Include:
   - summary of behavior changes,
   - sample command invocations,
   - tests for new or changed logic.
4. Ensure CI is green.

## Commit Style (required)

Enforced by the `commit-msg` pre-commit hook (`uv run pre-commit install`) and
by CI on every pull request (`scripts/check_commit_messages.py`); merge commits
are exempt.

Use the `[scope/op]: title` format with an imperative title under 72 characters.
Valid ops: `feat` `fix` `refactor` `test` `docs` `chore` `perf` `style` `ci`
`build` `revert`. Scope names a module or area (`cli`, `ops`, `core`, `pdf`,
`schema`, `release`, `repo`).

- `[cli/feat]: add json output for convert`
- `[core/fix]: preserve directory layout in output planner`
- `[repo/docs]: add automation examples`

Recommended body for non-trivial changes:

```
[scope/op]: title

What: one-line summary of the change
Why: motivation or issue reference
How: brief technical approach (if non-obvious)
```
