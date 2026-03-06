# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added

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
- Normalized destructive-flow safety with confirmation and dry-run behavior.
- Raised enforced test coverage gate to `50%`.

### Fixed

- Removed Pillow deprecation usage in compare engine data access.

