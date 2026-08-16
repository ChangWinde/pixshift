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
   uv build --sdist
   uv run twine check dist/*
   ```
2. Update `CHANGELOG.md`, set the same version in `pyproject.toml`, and run
   `uv lock`. Confirm that neither the tag nor package version already exists.
   The release workflow rejects a tag that differs from `project.version`.
3. Merge the reviewed release commit, then create and push an annotated version tag
   (use `-s` as well when a maintainer signing key is available):
   ```bash
   git tag -a vX.Y.Z -m "PixShift vX.Y.Z"
   git push origin vX.Y.Z
   ```
4. The tag-only `release.yml` workflow rejects lightweight or version-mismatched tags,
   runs the repository gate, builds the source distribution, then builds and executes
   authenticated runtime wheels on every target.
5. The publish job creates SHA-256 checksums and an SPDX SBOM, signs build-provenance and
   SBOM attestations through GitHub OIDC, publishes through PyPI trusted publishing, and
   creates the matching GitHub Release.
6. Download and verify artifacts, checksums, and attestations from GitHub Actions:
   ```bash
   gh attestation verify pixshift-*.whl -R ChangWinde/pixshift
   sha256sum --check SHA256SUMS
   ```

## Bundled Media Runtime

Normal local builds intentionally produce only a source distribution or a wheel without
native executables. The release workflow is the sole path that publishes runtime wheels:

1. `scripts/media_runtime_manifest.json` pins the FFmpeg version, upstream build commit,
   versioned artifact URLs, byte lengths, SHA-256 values, and wheel tags.
2. `scripts/stage_media_runtime.py` downloads into private temporary directories and
   publishes each file only after its length and digest match.
3. `scripts/verify_media_runtime.py` executes the pair on the target runner, verifies the
   codec/filter floor, and completes a real H.264/AAC encode plus ffprobe journey.
4. The wheel is retagged for exactly that OS/CPU, installed into a clean environment, and
   required to resolve its packaged provider before upload.

Updating the manifest is a security-sensitive change. Use the latest supported FFmpeg
security release, verify the upstream release and build commit, update every artifact
digest/size together, review the bundled license and codec configuration, then run the
local target smoke test. Never weaken a digest, use a floating URL, or make runtime media
commands download a missing artifact. The platform matrix currently covers
manylinux_2_28 x86-64/ARM64, macOS 15+ x86-64/ARM64, and Windows x86-64.

## Publish to PyPI (trusted publishing)

The tag-driven `release.yml` workflow contains a `publish` job that uploads the
validated artifacts to PyPI through [trusted publishing](https://docs.pypi.org/trusted-publishers/)
(OIDC, no long-lived API token). One-time setup:

1. On pypi.org, add a trusted publisher for project `pixshift`:
   owner `ChangWinde`, repository `pixshift`, workflow `release.yml`,
   environment `pypi`. The PyPI project already exists, so configure this under
   the existing project's Publishing settings (not as a pending publisher).
2. In the GitHub repository settings, create the `pypi` environment and require an
   explicit reviewer. Limit its deployment policy to `v*` tags.
3. Push a `vX.Y.Z` tag. The verification, source-build, and five platform-wheel matrix
   entries must all pass; the `publish` job uploads them only after the environment gate.

Never assume a green artifact build means PyPI was updated; verify the release
page on PyPI after the `publish` job succeeds.

## Documentation

The user manual publishes itself: `docs.yml` runs on every push to `main` that
touches `docs/` or `mkdocs.yml`, builds with `mkdocs build --strict`, uploads an
immutable Pages artifact, and deploys it through the `github-pages` environment to
<https://changwinde.github.io/pixshift/>. No release step or generated branch is required.

The expected hosted controls and audit commands live in
[repository-governance.md](repository-governance.md). Verify them before tagging; workflow
files alone cannot prove that rulesets, environments, or trusted publishers are active.

## Coverage Policy

The current repository-wide gate is `78%`. Increase this threshold only from a
fresh full-suite coverage report; historical measurements are not a release claim.
