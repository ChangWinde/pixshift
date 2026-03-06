# PixShift

<p align="center">
  <img src="assets/PixShift.png" alt="PixShift logo" width="280" />
</p>

[![CI](https://github.com/pixshift/pixshift/actions/workflows/ci.yml/badge.svg)](https://github.com/pixshift/pixshift/actions/workflows/ci.yml)
[![Release](https://github.com/pixshift/pixshift/actions/workflows/release.yml/badge.svg)](https://github.com/pixshift/pixshift/actions/workflows/release.yml)

PixShift is a high-performance CLI toolkit for daily image and PDF workflows.
It is designed for both direct terminal usage and automation-first pipelines.

## Why PixShift

- Fast batch operations with practical defaults
- Safe behavior for destructive actions
- Human-readable output and script-friendly JSON mode
- Modular architecture for long-term maintainability

## Installation

```bash
pip install pixshift
```

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

## Automation Mode (`--json`)

JSON mode is intended for CI and scripts.
In JSON mode, failures return non-zero exit codes.

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
- Command reference: `docs/COMMANDS.md`
- Phase checklist: `docs/PHASE1_CHECKLIST.md`
- JSON output contract: `docs/JSON_OUTPUT.md`
- First release PR pack: `docs/RELEASE_PR_FIRST.md`
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
