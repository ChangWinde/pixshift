# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Removed

- **Breaking:** the `watch` command. Long-running directory watching conflicts
  with the deterministic one-shot design; schedule `pixshift convert` with
  cron/launchd instead (ADR-0004).

### Added

- Video pillar (ADR-0005): optional ffmpeg-backed `video info / convert /
  compress / trim / thumbnail / extract-audio / gif` commands with pure,
  unit-testable argv builders, atomic outputs, stable `ffmpeg_missing`
  errors, and `doctor` reporting.
- Probe-driven `optimize` for videos: deterministic codec/bitrate analysis
  (no encoding) recommends `video.convert`, `video.compress`, or an explicit
  `keep` plan with a size estimate; results carry `media_type`.
- `apply` executes `video.convert` / `video.compress` plan steps under the
  image-step safety envelope (collision detection, idempotent skips,
  offline `--dry-run`) and treats `keep` as an explicit skip.
- `resize`: first-class same-format batch resizing (`--size`, `--percent`,
  `--max-size`) with `_resized` derivatives.
- `rotate`: clockwise rotation and mirroring with EXIF orientation normalized
  exactly once, producing `_rotated` derivatives.
- `pdf split`: split a PDF into per-page documents or one sub-range document.

- Forge commit convention (`[scope/op]: title`) documented in CONTRIBUTING and
  enforced via a `commit-msg` pre-commit hook, a CI check on pull-request
  commits, and dependabot commit prefixes.

- AI-native tool surface (ADR-0003): `pixshift tools` catalog with MCP-aligned
  side-effect annotations, and `pixshift apply` to execute `optimize` plans.
- Agent workflow commands: `prep` (bounded convert + privacy strip + hashed
  manifest), `manifest` (inventory with SHA-256 and sensitive-EXIF summary),
  and `hash` (content digests for audits).
- JSON Schema contracts in `docs/schemas/v1/` validated against live command
  output in CI.
- Thin MCP stdio adapter (`python -m pixshift.mcp`) mapping the catalog onto
  the CLI JSON contract.
- `python -m pixshift` module entry point.
- Positioning and governance docs: `GOAL.md`, `AGENTS.md`, ADR-0003, and a
  pre-commit configuration.

### Changed

- README repositioned around the AI-native discover/plan/apply/verify loop,
  with shell-completion instructions.
- Release workflow now publishes to PyPI via trusted publishing behind the
  `pypi` environment gate.
- PDF modules import `pymupdf` under its canonical name, removing the `fitz`
  deprecation warning from CLI output.
- `apply` steps without `--output` follow CLI derivative naming
  (`_compressed`, `_clean`) instead of colliding with the source file.
- Ruff lint scope extended (`W`, `C4`, `PIE`, `RUF`).
- Contributor workflow standardized on `uv sync --frozen --extra dev`.

## [1.1.0] - 2026-08-02

### Added

- A repository-wide policy test that rejects emoji in source, tests, documentation,
  examples, and configuration text.
- Machine-executable `optimize` plans with structured format estimates and sampling metadata.
- Successful CLI integration coverage for image watermarks and every PDF transformation.
- Shared generated-input filtering and idempotent existing-output skips for batch workflows.
- Stable JSON contract version (`schema_version: "1.0"`) for automation and AI clients.
- Shared path-policy, atomic-output, and orientation-normalization primitives.
- Regression coverage for traversal, collisions, failed overwrites, EXIF orientation,
  exact duplicate deletion, target-size bounds, and JSON failure exits.

- Advanced command set:
  - `compare`, `crop`, `watermark`, `montage`, `optimize`, `watch`.
- JSON mode for:
  - core workflow commands,
  - advanced commands,
  - system commands (`info`, `formats`, `doctor`),
  - PDF commands.
- `ops/` wrappers for convert/compress/strip/dedup/pdf/advanced workflows.
- Comprehensive command reference: `docs/COMMANDS.md`.
- Runnable example scripts:
  - `examples/automation/`,
  - `examples/advanced/`.
- Open-source governance and collaboration baseline:
  - issue templates,
  - PR template,
  - security/support/contributing docs,
  - CI and release workflows,
  - Dependabot.

### Changed

- Removed decorative emoji from CLI help, status messages, tables, summaries, comments,
  and descriptions; status is now expressed with concise text.
- Defaulted conversion/watch quality to `high`, PDF extraction to 150 DPI, and text
  watermark sizing to an image-relative value.
- Bounded large-image optimization trial encodes to a 1600 px sample (4.6× faster in
  the recorded 12 MP benchmark).
- Reduced montage peak memory by decoding one source at a time (58% in the recorded
  24-image benchmark).
- Made PNG/TIFF compression ignore lossy `--quality` values with a structured warning.
- Tightened PDF page-range, page-margin, font-path, and file-argument validation.
- Refactored CLI into modular command registration architecture.
- Unified file collection and output planning in shared core helpers.
- Tightened format support claims to runtime-detected capabilities.
- Preserved transparency for ICO conversion and watermark workflows.
- Normalized destructive-flow safety with confirmation and dry-run behavior.
- Limited automatic conversion workers to eight by default to avoid decoder memory pressure.
- Replaced quadratic perceptual-hash clustering with multi-index hashing.
- Simplified root help while keeping detailed per-command help.
- Switched CI/release dependency management to locked `uv` workflows and pinned actions.
- Raised enforced test coverage gate to `60%`.

### Fixed

- Removed sensitive device and personal fields stored in nested EXIF directories during
  default privacy cleanup while preserving metadata outside the selected categories.
- Rejected multi-frame inputs in still-image-only transformations and analyzers instead
  of silently replacing animations with their first frame.
- Excluded animations from perceptual deduplication while retaining byte-identical
  animation detection and reporting the skipped analysis count.
- Detected indexed transparency consistently and flattened it onto the configured
  background for opaque outputs.
- Required exact pixel and alpha equality for a perfect comparison rating.
- Kept empty deduplication analysis payloads consistent with the documented JSON schema.
- Prevented recursive/repeated workflows from consuming their own outputs or watermark assets.
- Made the documented "skip existing output" behavior idempotent instead of a failed batch.
- Prevented invalid or out-of-range PDF page selections from silently succeeding with no output.
- Rejected misleading comparisons across different aspect ratios and invalid/conflicting
  resize expressions; tiny percentage resizes now retain at least one pixel per dimension.
- Removed Pillow deprecation usage in compare engine data access.
- Prevented output path traversal, flattened-name collisions, recursive watch loops,
  recursive watch same-name overwrites, stale EXIF orientation, and partial overwrite
  corruption.
- Made target-size compression fail when the requested bound cannot be reached.
- Restricted automatic duplicate deletion to freshly revalidated byte-identical files.
- Made failed JSON operations return non-zero status consistently.
- Made Click parameter-validation failures machine-readable in `--json` mode.
- Distinguished required and optional capabilities in `doctor` exit semantics.
- Rejected montage extensions that do not match its PNG/JPEG/WebP encoders.
- Synchronized the runtime version with installed package metadata.
