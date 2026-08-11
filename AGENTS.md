# Agent Notes for PixShift

PixShift is a local-first, agent-safe image and PDF toolkit.

## How to call

1. Discover: `pixshift tools --json`
2. Inspect: `pixshift info PATH --json` or `pixshift manifest PATH -r --json`
3. Plan: `pixshift optimize PATH --json` (each result includes `plan`)
4. Apply: `pixshift apply --plan plan.json --json` (supports `--dry-run`)
5. Prepare assets: `pixshift prep PATH -o OUT --max-size 2048 -t webp --json`
6. Verify: `pixshift hash PATH --json` / `pixshift compare A B --json` / `pixshift doctor --json`

Always pass `--json` for machine use. Failures set `ok: false` and exit non-zero.

## Safety

- Prefer `--dry-run` before destructive work.
- `dedup --delete` only removes revalidated byte-identical files.
- Do not bypass path/output policy; the CLI enforces root containment and collisions.
- No network calls in the media hot path.

## Non-goals

Do not expect generative captioning, LoRA training, or ImageMagick-complete filters.
