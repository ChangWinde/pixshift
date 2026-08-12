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
   uv run pytest -q --cov=pixshift --cov-report=term-missing --cov-fail-under=78
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

## Publish to PyPI (trusted publishing)

The tag-driven `release.yml` workflow contains a `publish` job that uploads the
validated artifacts to PyPI through [trusted publishing](https://docs.pypi.org/trusted-publishers/)
(OIDC, no long-lived API token). One-time setup:

1. On pypi.org, add a trusted publisher for project `pixshift`:
   owner `ChangWinde`, repository `pixshift`, workflow `release.yml`,
   environment `pypi`. For a first release use a *pending* publisher.
2. In the GitHub repository settings, create the `pypi` environment.
   Recommended: require a reviewer so publishing stays an explicit decision.
3. Push a `vX.Y.Z` tag. The `build` job runs the full gate and builds artifacts;
   the `publish` job uploads them only after the environment gate passes.

Never assume a green artifact build means PyPI was updated; verify the release
page on PyPI after the `publish` job succeeds.

## Coverage Policy

The current repository-wide gate is `78%` (measured coverage is above 82%).
Increase this threshold gradually as module coverage improves; the next target is `85%`.
