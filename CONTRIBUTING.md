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

## Project Expectations

- Keep changes focused and minimal.
- Prefer typed functions and concise English comments.
- Maintain CLI UX consistency across commands.
- Add or update tests for behavior changes.
- Update docs when command behavior changes.

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

