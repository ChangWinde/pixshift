# Releasing PixShift

## Versioning

PixShift follows semantic versioning (`MAJOR.MINOR.PATCH`).

## Release Steps

1. Ensure tests pass locally:
   ```bash
   python -m pip install -e ".[dev]"
   python -m pytest -q --cov=pixshift --cov-report=term-missing --cov-fail-under=50
   ```
2. Update `CHANGELOG.md`.
3. Create and push a version tag:
   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
4. The `release.yml` workflow builds and validates package artifacts.
5. Download and verify artifacts from GitHub Actions.

## Optional: Publish to PyPI

After validating artifacts, publish with trusted publishing or twine from CI.

## Coverage Policy

The current repository-wide gate is a baseline (`50%`) to enforce trend safety.
Increase this threshold gradually as module coverage improves.

