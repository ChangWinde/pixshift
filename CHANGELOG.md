# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added

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
