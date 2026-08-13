# ADR-0004: Feature surface audit

## Status

Accepted

## Context

PixShift accumulated 19 leaf commands before the AI-native surface added five
more. An audit against the product positioning (deterministic, one-shot,
agent-safe local commands) and against widely used image CLIs (imgp, sharp,
ImageMagick) found one structural misfit and three first-class gaps.

## Driving Factors

- Every catalog entry costs agent context; each command must earn its place.
- Long-running daemons conflict with deterministic one-shot semantics.
- Resize and rotate are the two highest-frequency primitives of image CLIs,
  yet resize was only reachable through unintuitive `convert -f png -t png`
  semantics and rotate did not exist.
- Splitting a PDF into per-page or sub-range documents is a daily workflow;
  the engine already parses page ranges for `extract`.

## Candidates

### Option A: Keep the surface as-is

- Pros: no breaking change.
- Cons: keeps a daemon-style command with the weakest coverage (57%) and
  leaves the two most common primitives missing or hidden.

### Option B: Remove `watch`; add `resize`, `rotate`, `pdf split`

- Pros: surface matches positioning; first-class primitives become explicit;
  cron/launchd plus `convert` fully covers folder automation.
- Cons: removing `watch` is a breaking change for its users.

### Option C: Keep `watch` and also add the new commands

- Pros: no removal.
- Cons: the misfit remains and the catalog keeps growing without pruning.

## Decision

Chosen: **Option B**.

- `watch` is removed. Folder automation is documented as a scheduler recipe
  (`cron` / `launchd` invoking `pixshift convert`). Its `--once` mode was a
  `convert` alias with a duplicate-tracking cache that one-shot semantics do
  not need.
- `resize` becomes a first-class same-format batch command (`--size WxH`,
  `--percent`, `--max-size`), producing `_resized` derivatives.
- `rotate` becomes a first-class command (clockwise 90/180/270 plus mirror),
  normalizing EXIF orientation exactly once, producing `_rotated` derivatives.
- `pdf split` writes per-page PDFs by default and a single sub-document with
  `--single`, reusing the existing page-range parser.

Audited and kept deliberately: `manifest` vs `hash` (media inventory for
decisions vs generic digests for audits), `montage` (agents build contact
sheets to present results), `formats` vs `doctor` and `pdf merge` vs
`pdf concat` (ADR-0002).

## Impact

- Breaking: the `watch` command and its JSON payload are removed; the next
  release must bump the minor version and state the migration recipe.
- New commands enter the tool catalog, docs, schemas coverage via the shared
  envelope, and the test suite.
- Animated-image transforms (GIF/APNG to WebP) stay out of scope for this
  audit and are tracked as a roadmap item in docs/GOAL.md.
