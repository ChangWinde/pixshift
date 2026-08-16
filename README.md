# PixShift

<p align="center">
  <img src="https://raw.githubusercontent.com/ChangWinde/pixshift/main/.github/assets/PixShift.png" alt="PixShift logo" width="280" />
</p>

<p align="center">
  Local-first media operations for people, scripts, and agents.
</p>

[![CI](https://img.shields.io/github/actions/workflow/status/ChangWinde/pixshift/ci.yml?branch=main&label=CI)](https://github.com/ChangWinde/pixshift/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/github/actions/workflow/status/ChangWinde/pixshift/docs.yml?branch=main&label=Docs)](https://changwinde.github.io/pixshift/)
[![PyPI](https://img.shields.io/pypi/v/pixshift)](https://pypi.org/project/pixshift/)
[![Python](https://img.shields.io/pypi/pyversions/pixshift)](https://pypi.org/project/pixshift/)
[![License](https://img.shields.io/github/license/ChangWinde/pixshift)](https://github.com/ChangWinde/pixshift/blob/main/LICENSE)

PixShift is a deterministic CLI toolkit for everyday image, PDF, and video work.
Humans get concise terminal output; scripts and agents get the same operations through
schema-validated JSON, executable plans, explicit side-effect metadata, and stable exit
codes. Media processing stays on the local machine.

[中文使用手册](https://changwinde.github.io/pixshift/) ·
[安装](https://changwinde.github.io/pixshift/install/) ·
[自动化](https://changwinde.github.io/pixshift/automation/) ·
[贡献指南](https://github.com/ChangWinde/pixshift/blob/main/.github/CONTRIBUTING.md) ·
[更新记录](https://github.com/ChangWinde/pixshift/blob/main/CHANGELOG.md)

## Why PixShift

| Need | What PixShift guarantees |
| --- | --- |
| One media toolbox | Focused commands across images, PDFs, and video instead of a hidden mega-pipeline |
| Best quality under a byte limit | `--target-size` searches the complete bounded quality domain for images and PDFs; video uses bounded bitrate strategies |
| Safe automation | Full-batch planning, collision rejection, root-contained atomic publication, stable JSON errors, and dry runs |
| Faithful delivery | ICC-aware image comparison, animation timing checks, PDF semantic inventories, and video audio/video verification |
| Local operation | No network or model call in the media-processing hot path; standard installs include a local video runtime |

PixShift deliberately does not provide generative editing, cloud transcoding, a video
timeline editor, or an ImageMagick-complete filter language. Its scope is auditable,
one-shot media work.

## Install

Python 3.10 or newer is required. The published release installs with:

```bash
pip install pixshift
# or: uv tool install pixshift
```

The documentation and this README follow `main`, so they can be ahead of the latest
published package. To use exactly the documented surface:

```bash
git clone https://github.com/ChangWinde/pixshift.git
cd pixshift
pip install .
```

Image codecs (including HEIC/HEIF and AVIF), PDF support, and a local FFmpeg 8.1.2 pair
ship in supported release wheels. If a complete system ffmpeg/ffprobe pair is already on
`PATH`, PixShift prefers it; otherwise it uses the wheel-packaged pair without downloading
anything at command time. Source/editable installs deliberately use a system pair instead
of fetching native files during a build. `pixshift doctor --json` reports the selected
runtime and exact capabilities.

See the [installation guide](https://changwinde.github.io/pixshift/install/) for macOS,
Linux, Windows, uv, and shell-completion instructions.

## Sixty-second tour

```bash
# Inspect local capabilities
pixshift doctor --json

# Convert a directory while colour-managing output to sRGB
pixshift convert ./photos -t webp -q high --color-space srgb -r --json

# Keep the best JPEG quality that fits 500 KB
pixshift compress poster.jpg --target-size 500KB --json

# Build and split PDFs
pixshift pdf merge ./scans -o album.pdf --json
pixshift pdf split report.pdf -o ./pages --json

# Compress video to a delivery budget
pixshift video compress talk.mp4 --target-size 25MB --audio-policy compatible --json

# Prove the candidate still satisfies media-specific structure and quality gates
pixshift verify source.jpg candidate.webp --min-ssim 0.99 --json
```

Existing derivative outputs are skipped by default. Use `--overwrite` only when
replacement is intentional, and preview destructive duplicate cleanup with
`dedup --delete --dry-run` before confirming it.

## Choose the operation

| Job | Images | PDFs | Video |
| --- | --- | --- | --- |
| Inspect | `info`, `manifest`, `hash` | `pdf info` | `video info` |
| Convert | `convert` | `pdf extract` | `video convert` |
| Compress to a preset or size | `compress` | `pdf compress` | `video compress` |
| Transform | `crop`, `resize`, `rotate` | `pdf split` | `video trim`, `video thumbnail` |
| Compose | `montage`, `watermark` | `pdf merge`, `pdf concat` | `video concat`, `video gif` |
| Clean or analyse | `strip`, `dedup`, `compare`, `optimize` | `verify` | `video extract-audio`, `verify` |
| Prepare for delivery | `prep` | `verify` | `verify` |

The complete command reference is split by pillar:
[images](https://changwinde.github.io/pixshift/images/),
[PDF](https://changwinde.github.io/pixshift/pdf/), and
[video](https://changwinde.github.io/pixshift/video/).

## Agent and automation contract

The recommended loop is discover, inspect, plan, dry-run, apply, and verify:

```bash
pixshift tools --json
pixshift manifest ./media -r --json
pixshift optimize ./media -r --json > plan.json
pixshift apply --plan plan.json -o ./out --dry-run --json
pixshift apply --plan plan.json -o ./out --json
pixshift verify source.png ./out/source.webp --json
```

Automation guarantees:

- Every JSON document includes `"schema_version": "1.1"`, `command`, and `ok`.
- Exit `0` is success, `1` is an attempted operation that failed, and `2` is a
  pre-write usage or plan rejection.
- `pixshift tools --json` publishes MCP-aligned read-only, destructive,
  idempotent, and open-world annotations.
- `pixshift apply --dry-run` performs the same plan validation as execution without
  writing media outputs.
- `python -m pixshift.mcp` exposes a bounded stdio JSON-RPC adapter over the same CLI
  contract; it is not a second implementation of the engines.

The [automation guide](https://changwinde.github.io/pixshift/automation/) and
[JSON contract](https://changwinde.github.io/pixshift/JSON_OUTPUT/) document the
public interface. Versioned schemas live in
[`docs/schemas/v1/`](https://github.com/ChangWinde/pixshift/tree/main/docs/schemas/v1).

## Safety and quality boundaries

- Output paths are planned as a batch before the first write. Collisions, path escapes,
  and aggregate source/output aliases are rejected.
- Encoders publish atomically and preserve no-clobber semantics at commit time on POSIX
  and Windows.
- Pixel budgets are checked before large decodes, including aggregate animation frames
  and generated montage/PDF pages.
- Animation is preserved with its frame timing and loop semantics, or explicitly refused;
  it is never silently flattened.
- Similarity groups are advisory. `dedup --delete` removes only byte-identical files after
  an immediate identity and SHA-256 recheck.
- `verify` compares media-specific structure as well as raster similarity: colour and alpha
  for images, document semantics for PDFs, and audio plus video for containers.

These are implementation contracts, not slogans. Their rationale is recorded in the
[architecture overview](https://github.com/ChangWinde/pixshift/blob/main/docs/project/architecture.md)
and [architecture decisions](https://github.com/ChangWinde/pixshift/tree/main/docs/adr/),
and their observable behavior is covered by the cross-platform test suite.

## Repository map

```text
pixshift/              Python package: commands, ops, engines, and shared policy
tests/                 Tests grouped by automation, CLI, core, media pillar, and integration
docs/                  Published manual plus schemas
docs/project/          Maintainer architecture, governance, goals, and release notes
docs/adr/              Immutable architecture decision records
examples/              Runnable human and automation workflows
scripts/               Repository verification and benchmark utilities
.github/               Community policy, templates, workflows, and brand assets
```

The test grouping and placement rules are described in
[`tests/README.md`](https://github.com/ChangWinde/pixshift/blob/main/tests/README.md).

Root files are intentionally limited to tools that rely on conventional discovery:
package and lock metadata, the source-distribution manifest, MkDocs and pre-commit
configuration, the agent guide, license, changelog, and this README. The placement policy
and update matrix are documented in
[`docs/project/documentation-governance.md`](https://github.com/ChangWinde/pixshift/blob/main/docs/project/documentation-governance.md).

Hosted branch, tag, Pages, scanning, and release controls are documented in
[`docs/project/repository-governance.md`](https://github.com/ChangWinde/pixshift/blob/main/docs/project/repository-governance.md).
Release packages include SHA-256 checksums, an SPDX SBOM, and GitHub-verifiable build and
SBOM attestations before trusted-publisher upload to PyPI.

## Contributing

Start with the
[contributor guide](https://github.com/ChangWinde/pixshift/blob/main/.github/CONTRIBUTING.md).
The required local gate is:

```bash
uv sync --frozen --extra dev
uv run ruff check .
uv run ruff format --check .
uv run mypy . --ignore-missing-imports
uv run pytest -q --cov=pixshift --cov-fail-under=78
uv run mkdocs build --strict
```

Security reports use
[private GitHub advisories](https://github.com/ChangWinde/pixshift/blob/main/.github/SECURITY.md);
usage questions follow the
[support guide](https://github.com/ChangWinde/pixshift/blob/main/.github/SUPPORT.md).

## License

PixShift is released under the
[MIT License](https://github.com/ChangWinde/pixshift/blob/main/LICENSE).
