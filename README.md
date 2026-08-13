# PixShift

<p align="center">
  <img src="https://raw.githubusercontent.com/ChangWinde/pixshift/main/assets/PixShift.png" alt="PixShift logo" width="280" />
</p>

[![CI](https://img.shields.io/github/actions/workflow/status/ChangWinde/pixshift/ci.yml?branch=main&label=CI)](https://github.com/ChangWinde/pixshift/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/actions/workflow/status/ChangWinde/pixshift/release.yml?label=Release)](https://github.com/ChangWinde/pixshift/actions/workflows/release.yml)
[![Docs](https://img.shields.io/github/actions/workflow/status/ChangWinde/pixshift/docs.yml?label=Docs)](https://changwinde.github.io/pixshift/)

PixShift is an AI-native, local-first CLI toolkit for daily media work across three
pillars — images, PDFs, and video. Humans get fast commands with rich output; agents and
scripts get a discoverable tool catalog, schema-validated JSON contracts, and executable
plans over the same deterministic engines.

Full documentation: **<https://changwinde.github.io/pixshift/>**

## Why PixShift

- AI-native surface: `tools` catalog with side-effect annotations, `optimize`
  plans, `apply` execution, and schema contracts under `docs/schemas/v1/`
- The size-budget idiom on every pillar: `--target-size 25MB` keeps the best
  quality that fits (binary search for images, quality-ladder search for
  PDFs, two-pass bitrate encoding for video)
- Fast batch operations with practical defaults; batches parallelise across
  a bounded worker pool automatically
- Idempotent reruns: discovered generated files are ignored and existing outputs are skipped
- Safe destructive behavior: similarity is advisory; only revalidated,
  byte-identical duplicates can be deleted
- Human-readable output and script-friendly JSON mode with stable failure exit codes
- Local media hot path: no model or network call sits between you and your files
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
├─ resize       Resize images keeping their format
├─ rotate       Rotate or mirror images
├─ watermark    Add text/image watermark
├─ montage      Build image grid montage
├─ optimize     Recommend best output format
├─ info         Inspect image metadata and properties
├─ formats      Show supported formats and quality presets
├─ doctor       Validate runtime dependencies
├─ tools        List the agent-facing tool catalog
├─ apply        Execute machine plans from optimize
├─ prep         Prepare delivery-ready assets (resize + convert + privacy strip)
├─ manifest     Inventory media with hashes and properties
├─ hash         Compute content hashes for audits
├─ pdf
│  ├─ merge     Merge images into PDF
│  ├─ extract   Extract PDF pages as images
│  ├─ split     Split PDF into separate PDFs
│  ├─ compress  Compress PDF
│  ├─ concat    Concatenate multiple PDFs
│  └─ info      Show PDF details
└─ video        (needs ffmpeg)
   ├─ info          Inspect container/codecs/duration
   ├─ convert       Transcode to mp4/webm/mkv/mov
   ├─ compress      Shrink with CRF presets or fit a size budget
   ├─ concat        Join clips end to end (lossless stream copy)
   ├─ trim          Cut a time range (stream-copy by default)
   ├─ thumbnail     Extract a still frame
   ├─ extract-audio Export the audio track
   └─ gif           Convert a clip to animated GIF
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
pixshift resize ./photos/ --max-size 1600 -r
pixshift rotate ./scans/ --degrees 90
pixshift watermark text ./photos/ --text "© PixShift" -r
pixshift montage ./photos/ -o board.png --cols 4
pixshift optimize ./photos/ -r
pixshift pdf merge ./photos/ -o album.pdf
pixshift pdf split ./report.pdf -o ./pages/
pixshift video compress ./clips/ -p web -r      # needs ffmpeg
pixshift video thumbnail demo.mp4 --at 25%
pixshift video gif demo.mp4 -o demo.gif --fps 15 --width 480
```

Video commands require a system `ffmpeg`/`ffprobe` (`brew install ffmpeg` or
`apt install ffmpeg`); `pixshift doctor` reports availability. They are never required
for the image and PDF pillars.

Common defaults favor everyday speed without hiding control: conversion uses `high`
quality, PDF extraction uses 150 DPI, text-watermark size adapts to the image, and
existing batch outputs are skipped. Use `-q max`, `--dpi 300`, `--font-size 36`, or
`--overwrite` when those explicit behaviors are required.

## AI-Native Interface

Agents discover, plan, apply, and verify with four moves:

```bash
pixshift tools --json                          # discover: catalog + annotations
pixshift optimize ./photos -r --json > plan.json   # plan: executable recommendations
pixshift apply --plan plan.json -o ./out --json    # apply: run the plan (supports --dry-run)
pixshift hash ./out -r --json                  # verify: content digests for audit
```

- Every tool entry carries MCP-aligned annotations (`readOnlyHint`,
  `destructiveHint`, `idempotentHint`, `openWorldHint: false`).
- JSON payload contracts live in `docs/schemas/v1/` and are validated in CI.
- One-shot asset preparation: `pixshift prep ./raw -o ./dist --max-size 2048 -t webp --json`
  converts, bounds dimensions, strips privacy metadata, and returns a hashed manifest.
- Directory inventory: `pixshift manifest ./photos -r --json` reports formats,
  dimensions, alpha, frame counts, sensitive EXIF keys, and SHA-256 digests.
- Optional MCP hosting: `python -m pixshift.mcp` serves the same catalog over
  stdio JSON-RPC; the CLI JSON document remains the authoritative contract
  (see `docs/adr/0003-ai-native-tool-surface.md`).
- Agent guide: `AGENTS.md`.

## Shell Completion

Click provides completion for bash, zsh, and fish:

```bash
# bash (~/.bashrc)
eval "$(_PIXSHIFT_COMPLETE=bash_source pixshift)"
# zsh (~/.zshrc)
eval "$(_PIXSHIFT_COMPLETE=zsh_source pixshift)"
# fish (~/.config/fish/completions/pixshift.fish)
_PIXSHIFT_COMPLETE=fish_source pixshift | source
```

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
pixshift resize ./photos/ --percent 50 --json
pixshift rotate ./scans/ --degrees 90 --json
pixshift watermark text ./photos/ --text "© PixShift" --dry-run --json
pixshift montage ./photos/ -o board.png --json
pixshift optimize ./photos/ --json
pixshift info ./photo.jpg --json
pixshift formats --json
pixshift doctor --json
pixshift pdf info ./report.pdf --json
pixshift pdf split ./report.pdf -o ./pages/ --json
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
- AI-native surface ADR: `docs/adr/0003-ai-native-tool-surface.md`
- Feature surface audit ADR: `docs/adr/0004-feature-surface-audit.md`
- Video pillar ADR: `docs/adr/0005-video-pillar.md`
- JSON Schema contracts: `docs/schemas/v1/`
- Agent guide: `AGENTS.md`
- Project goal and milestones: `docs/GOAL.md`
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
- `.github/CODE_OF_CONDUCT.md`
- `.github/SECURITY.md`
- `.github/SUPPORT.md`
- `.github/ISSUE_TEMPLATE/*`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/workflows/ci.yml`

## License

This project is licensed under the MIT License. See `LICENSE`.
