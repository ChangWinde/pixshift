# PixShift

PixShift is an **AI-native, local-first CLI toolkit** for daily media work across
three pillars — **images, PDFs, and video**. Humans get fast commands with rich
output; agents and scripts get a discoverable tool catalog, schema-validated
JSON contracts, and executable plans over the same deterministic engines.

## Install

```bash
pip install pixshift
```

Requires Python `>=3.10`. PDF commands use PyMuPDF (bundled); video commands
use ffmpeg (optional system dependency, reported by `pixshift doctor`).

## Quickstart — humans

```bash
pixshift convert photo.heic -t webp                  # convert one file
pixshift convert banner.gif -t webp                  # animated GIF -> animated WebP
pixshift compress ./exports -p web -r                # batch-compress a folder
pixshift compress poster.jpg --target-size 500KB     # best quality under a size cap
pixshift strip secret.jpg                            # remove privacy metadata
pixshift pdf merge scans/*.png -o doc.pdf            # images into a PDF
pixshift pdf compress scan.pdf --target-size 2MB     # fit a PDF into a byte budget
pixshift video compress talk.mp4 --target-size 25MB  # two-pass fit (needs ffmpeg)
pixshift video concat a.mp4 b.mp4 -o joined.mp4      # lossless stream-copy join
```

## Quickstart — agents

The whole surface closes a **discover → plan → apply → verify** loop with
stable JSON on every step:

```bash
pixshift tools --json                                  # discover the catalog
pixshift optimize ./media --json                       # plan (images + videos)
pixshift optimize ./media --json | pixshift apply --plan - --dry-run --json
pixshift hash ./media -r --json                        # verify with digests
```

Every failure sets `ok: false` and a non-zero exit; every payload carries
`schema_version` and validates against the contracts in
[`docs/schemas/v1/`](https://github.com/ChangWinde/pixshift/tree/main/docs/schemas/v1).
Plans are deterministic and portable: video analysis is probe-driven (nothing
is encoded at plan time) and an already-efficient file gets an explicit
`keep` plan.

## Safety invariants

- Atomic writes: outputs appear complete or not at all.
- Idempotent reruns: existing outputs are skipped unless `--overwrite` is set.
- Destructive actions are opt-in and revalidated (`dedup --delete` removes
  only byte-identical duplicates).
- No model or network call sits in the media hot path.

## Where next

- [Commands](COMMANDS.md) — the full command reference, including the video
  pillar and hardware-accelerated encoding.
- [JSON Output](JSON_OUTPUT.md) — the machine contract for every command.
- [Architecture](ARCHITECTURE.md) and the ADRs — why PixShift behaves the
  way it does.
