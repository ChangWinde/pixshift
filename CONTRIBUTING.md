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
uv run pytest -q --cov=pixshift --cov-fail-under=70
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

## Commit Style (recommended)

Use clear, imperative messages:

- `feat: add json output for convert`
- `fix: preserve directory layout in output planner`
- `docs: add automation examples`

