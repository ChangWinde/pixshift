# ADR 0002: Opinionated Defaults and Machine-Executable Plans

- Status: Accepted
- Date: 2026-08-02

## Context

PixShift exposes 19 leaf commands. The commands cover distinct user jobs, but several defaults
and boundaries made common workflows less predictable:

- `convert` and `watch` defaulted to the slowest, largest `max` encoding preset.
- `pdf extract` rendered at 300 DPI by default. A 12-page A4 benchmark took 0.869 seconds and
  produced 864 KB, compared with 0.281 seconds and 334 KB at 150 DPI.
- Recursive or repeated batch runs could rediscover prior outputs and process them again.
- `compress --quality` appeared to control PNG/TIFF quality even though those formats use
  lossless compression effort instead of visual quality.
- `optimize` calculated format estimates internally but returned only a display-oriented label,
  leaving automation to reverse-engineer a command.
- Text watermark size was fixed at 36 px regardless of image dimensions.

The product should remain simple for terminal users while becoming deterministic and useful for
automation and AI agents.

## Options Considered

### 1. Preserve every default and only fix crashes

This has the lowest compatibility cost, but retains slow common paths, repeated-output growth,
and an incomplete automation contract.

### 2. Keep command boundaries, improve defaults, and expose structured plans

Each command remains responsible for one user job. Shared input planning excludes generated
artifacts discovered through directories, defaults optimize for the common case, and analysis
commands return structured next actions. Existing explicit options and documented JSON fields
remain valid.

### 3. Replace specialist commands with one automatic `run` command

This reduces the visible command count, but makes destructive behavior and quality choices more
implicit. It also creates a large compatibility break and makes automation harder to audit.

## Decision

Choose option 2.

- Keep all current leaf commands. `convert` versus `compress`, image-to-PDF `merge` versus
  PDF-to-PDF `concat`, and capability `formats` versus environment `doctor` represent distinct
  jobs rather than redundant aliases.
- Default image conversion and watch conversion to `high`; users can still request `max`.
- Default PDF page extraction to 150 DPI; higher DPI remains explicit.
- Use automatic text-watermark sizing when `--font-size` is omitted.
- Apply generated-input filtering only to files discovered through directory scans. Explicit file
  arguments remain authoritative, except that an operation's own output or watermark asset can
  never become an input accidentally.
- Treat `compress --quality` as a lossy-codec control. PNG and TIFF retain their preset-driven
  lossless compression settings, with a structured warning when a requested quality is ignored.
- Make `optimize` return estimates, sampling metadata, and a structured executable plan. Large
  images are analyzed on a bounded 1600 px sample and report that estimates are sampled. A local
  12 MP encoder benchmark dropped from 7.055 seconds at full resolution to 1.542 seconds for the
  bounded analysis phase.
- Preserve JSON schema version `1.0`: these are additive fields, not removals or type changes to
  existing documented fields.

## Consequences

- Common conversion and extraction are materially faster and produce smaller outputs.
- Re-running a directory workflow does not recursively amplify generated files.
- Automation can execute an optimization recommendation without parsing localized prose.
- Users relying on the old implicit `max`, 300 DPI, or fixed 36 px watermark defaults must pass
  those values explicitly.
- Sampled optimization sizes are estimates, not byte-accurate predictions; the payload identifies
  the sampling basis so callers can communicate that uncertainty.
