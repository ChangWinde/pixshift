# Releasing PixShift

## Versioning

PixShift follows semantic versioning (`MAJOR.MINOR.PATCH`).

## Release Steps

1. Ensure tests pass locally:
   ```bash
   uv sync --frozen --extra dev
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy . --ignore-missing-imports
   uv run pytest -q --cov=pixshift --cov-report=term-missing --cov-fail-under=70
   uv build
   uv run twine check dist/*
   ```
2. Update `CHANGELOG.md`, set the same version in `pyproject.toml`, and run
   `uv lock`. Confirm that neither the tag nor package version already exists.
3. Merge the reviewed release commit, then create and push a version tag:
   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
4. The tag-only `release.yml` workflow tests, builds, validates, and uploads package artifacts.
5. Download and verify artifacts from GitHub Actions.

## Optional: Publish to PyPI

The current workflow does **not** publish to PyPI. After validating artifacts, publish
with trusted publishing or add an explicitly reviewed publish job. Never assume a green
artifact build means PyPI was updated.

## Coverage Policy

The current repository-wide gate is `70%` (measured coverage is above 75%).
Increase this threshold gradually as module coverage improves; the next target is `80%`.
