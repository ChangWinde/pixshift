# Agent Notes for PixShift

PixShift is a local-first, agent-safe image, PDF, and video toolkit.

## How to call

1. Discover: `pixshift tools --json`
2. Inspect: `pixshift info PATH --json`, `pixshift video info PATH --json`,
   or `pixshift manifest PATH -r --json`
3. Plan: `pixshift optimize PATH --json` (each result includes `plan`;
   videos are analysed from probe metadata and may plan `keep` = no action)
4. Apply: `pixshift apply --plan plan.json --json` (supports `--dry-run`)
5. Prepare assets: `pixshift prep PATH -o OUT --max-size 2048 -t webp --json`
6. Verify: `pixshift hash PATH --json` / `pixshift compare A B --json` / `pixshift doctor --json`

Always pass `--json` for machine use. Failures set `ok: false` and exit
non-zero: `1` means work was attempted and something failed (see the
`errors` objects: `input`/`output`/`error`), `2` means the invocation was
rejected before any output was written (bad arguments or plan validation).
Video commands need ffmpeg (optional, reported by `doctor`); without it they
fail with a stable `ffmpeg_missing` error.

## Safety

- Prefer `--dry-run` before destructive work.
- `dedup --delete` only removes revalidated byte-identical files.
- Do not bypass path/output policy; the CLI enforces root containment and collisions.
- No network calls in the media hot path.

## Non-goals

Do not expect generative captioning, LoRA training, or ImageMagick-complete filters.
