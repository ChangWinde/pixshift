# PixShift

<p align="center">
  <img src="https://raw.githubusercontent.com/ChangWinde/pixshift/main/assets/PixShift.png" alt="PixShift logo" width="280" />
</p>

[![CI](https://img.shields.io/github/actions/workflow/status/ChangWinde/pixshift/ci.yml?branch=main&label=CI)](https://github.com/ChangWinde/pixshift/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/actions/workflow/status/ChangWinde/pixshift/release.yml?label=Release)](https://github.com/ChangWinde/pixshift/actions/workflows/release.yml)

PixShift is a high-performance CLI toolkit for daily image and PDF workflows.
It is designed for both direct terminal usage and automation-first pipelines.

## Why PixShift

- Fast batch operations with practical defaults
- Idempotent reruns: discovered generated files are ignored and existing outputs are skipped
- Safe destructive behavior: similarity is advisory; only revalidated,
  byte-identical duplicates can be deleted
- Human-readable output and script-friendly JSON mode
- AI-ready optimization plans with structured arguments, estimates, and uncertainty metadata
- Modular architecture for long-term maintainability

## Installation

```bash
pip install pixshift
```

Requires Python `>=3.10`.

## Command Tree

```text
pixshift
├─ convert      Convert image formats
├─ compress     Compress images in the same format
├─ strip        Remove metadata (privacy cleanup)
├─ dedup        Find and remove similar/duplicate images
├─ compare      Compare image quality (SSIM/PSNR/MSE)
├─ crop         Crop images by box/aspect/auto-trim
├─ watermark    Add text/image watermark
├─ montage      Build image grid montage
├─ optimize     Recommend best output format
├─ watch        Watch directory and auto-convert
├─ info         Inspect image metadata and properties
├─ formats      Show supported formats and quality presets
├─ doctor       Validate runtime dependencies
└─ pdf
   ├─ merge     Merge images into PDF
   ├─ extract   Extract PDF pages as images
   ├─ compress  Compress PDF
   ├─ concat    Concatenate multiple PDFs
   └─ info      Show PDF details
```

## Quick Start

```bash
pixshift convert ./photos/ -t webp -q high -r
pixshift compress ./photos/ -p medium -r
pixshift strip ./photos/ --mode privacy -r
pixshift dedup ./photos/ -r --delete --dry-run
pixshift dedup ./photos/ -r --delete --yes
pixshift compare a.jpg b.jpg
pixshift crop ./photos/ --aspect 1:1 -r
pixshift watermark text ./photos/ --text "© PixShift" -r
pixshift montage ./photos/ -o board.png --cols 4
pixshift optimize ./photos/ -r
pixshift watch ./incoming --once -t webp
pixshift pdf merge ./photos/ -o album.pdf
```

Common defaults favor everyday speed without hiding control: conversion uses `high`
quality, PDF extraction uses 150 DPI, text-watermark size adapts to the image, and
existing batch outputs are skipped. Use `-q max`, `--dpi 300`, `--font-size 36`, or
`--overwrite` when those explicit behaviors are required.

## Automation Mode (`--json`)

JSON mode is intended for CI and scripts.
In JSON mode, failures return non-zero exit codes.
Every document includes `"schema_version": "1.0"`, `command`, and `ok`.

```bash
pixshift convert ./photos/ -t webp --json
pixshift compress ./photos/ -p medium --json
pixshift strip ./photos/ --mode privacy --json
pixshift dedup ./photos/ -r --json
pixshift compare a.jpg b.jpg --json
pixshift crop ./photos/ --aspect 16:9 --dry-run --json
pixshift watermark text ./photos/ --text "© PixShift" --dry-run --json
pixshift montage ./photos/ -o board.png --json
pixshift optimize ./photos/ --json
pixshift watch ./incoming --once --json
pixshift info ./photo.jpg --json
pixshift formats --json
pixshift doctor --json
pixshift pdf info ./report.pdf --json
```

Script templates:

- `examples/automation/dedup_ci.sh`
- `examples/automation/compress_report.sh`
- `examples/automation/pdf_info_export.sh`
- `examples/advanced/README.md`

## Documentation

- Architecture: `docs/ARCHITECTURE.md`
- Safety boundary ADR: `docs/adr/0001-safe-operation-boundaries.md`
- Command reference: `docs/COMMANDS.md`
- Phase checklist: `docs/PHASE1_CHECKLIST.md`
- JSON output contract: `docs/JSON_OUTPUT.md`
- Performance evidence: `docs/PERFORMANCE.md`
- Product defaults ADR: `docs/adr/0002-opinionated-defaults-and-ai-plans.md`
- Label strategy: `docs/LABEL_STRATEGY.md`
- Automation examples: `examples/automation/README.md`
- Advanced examples: `examples/advanced/README.md`
- Release process: `docs/RELEASING.md`
- Changelog: `CHANGELOG.md`

## Contributing

Please read:

- `CONTRIBUTING.md`
- `CODE_OF_CONDUCT.md`
- `SECURITY.md`
- `SUPPORT.md`
- `.github/ISSUE_TEMPLATE/*`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/workflows/ci.yml`

## License

This project is licensed under the MIT License. See `LICENSE`.
