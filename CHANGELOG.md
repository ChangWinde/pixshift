# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added

- Batch selection filters shared by every batch command: `--include GLOB`,
  `--exclude GLOB` and `--min-file-size SIZE` narrow a run without shell
  gymnastics. Globs match both the full path and the bare name, so
  `--exclude '*/thumbs/*'` and `--exclude '*_draft.jpg'` both read naturally;
  unlike the automatic generated-file exclusion, these are an explicit
  instruction and therefore also apply to named files.
- A pixel budget that refuses decompression bombs before decoding: an image
  declaring more than 120 megapixels fails with the stable `image_too_large`
  error instead of exhausting memory. `PIXSHIFT_MAX_PIXELS` adjusts or
  disables PixShift's additional limit; Pillow's independent process policy
  remains in force.
- `dedup --backup-dir DIR` moves duplicates into a directory instead of
  deleting them, making the only destructive operation reversible; colliding
  names get a numeric suffix rather than overwriting each other.

### Changed

- Five engines (compress, strip, crop, watermark, montage) each carried their
  own copy of the directory-walking collector; they now delegate to the
  shared one in `core/files.py`, which is what gives every command the new
  filters at once.

### Fixed

- Image opens now enforce the pixel budget at one boundary without replacing
  Pillow globals or warning filters in host applications. Animated conversion
  checks every frame and the aggregate frame budget before decoding copies.
- PDF merge/concat and video concat reject an aggregate output that aliases an
  input, including files discovered through directory scans. PDF compression
  preserves both soft masks and colour-key masks, and the JPEG splice path no
  longer carries comments or trailing bytes placed after scan data.
- Video batches validate every destination before the first encode, ignore
  prior cross-container `_compressed` derivatives, reap ffmpeg after caller
  interruption, and refuse missing or zero-byte encoder outputs without
  replacing an existing destination.
- The MCP stdio adapter validates JSON-RPC envelopes and tool schemas, accepts
  only strict JSON, starts isolated CLI process groups, and terminates the
  whole group on timeout instead of leaving workers or ffmpeg running.

## [1.3.0] - 2026-08-13

### Fixed

- Non-finite numeric inputs are rejected across the video contracts:
  `"inf"`/`"nan"` timecodes raise `invalid_timecode` instead of flowing into
  ffmpeg arguments, malformed ffprobe frame rates and durations degrade to
  "no signal" instead of crashing `optimize` size estimates (previously an
  `OverflowError`) or serializing invalid JSON (`Infinity`).
- One broken file in a scanned directory no longer poisons the whole
  `optimize | apply` pipe: error entries carry an empty `plan` object since
  schema 1.1, and `apply` now skips them instead of rejecting the document
  with `missing_command` (found by the end-to-end sweep).
- HEIC/AVIF plugin registration moved to package import, so worker-pool
  children under spawn/forkserver start methods (the Linux default since
  Python 3.14) can decode them: previously a `compress`/`strip` pool child
  failed with "cannot identify image file" on HEIC while `convert` children
  happened to work (found by the sweep's HEIC corpus).
- Windows works now — the first-ever Windows CI run surfaced three
  platform bugs, all fixed: `os.fsync` on a read-only handle fails with
  EBADF there, so every atomic output write failed ("[Errno 9] Bad file
  descriptor"); the platform code page (cp1252/GBK) crashed any `--json`
  payload carrying Chinese text, so the machine channel and the MCP server
  now write UTF-8 bytes; and the animated convert path saved while the
  source was still open, which Windows' non-POSIX replace semantics
  reject for in-place `--overwrite`. macOS passed on first contact.
- `optimize` no longer emits an infinite bits-per-pixel figure when a crafted
  container reports a subnormal frame rate — the overflowing division now
  degrades to "no signal" (found by randomized property fuzzing).

### Added

- Animated-image transforms (the ADR-0004 gap): `convert` and `resize`
  preserve frames, per-frame timing, loop count, and transparency for GIF /
  APNG / animated WebP when the target format can animate (`webp`, `gif`,
  `png`); targets that cannot keep the stable `animated_input_not_supported`
  error instead of dropping frames.
- `optimize` classifies animations instead of rejecting them: animated
  GIF/APNG get an executable `convert -t webp` plan (animation preserved),
  an already-animated WebP gets an explicit `keep` plan.
- The size-budget idiom on every pillar: `video compress --target-size`
  (two-pass bitrate encoding for h264/h265/vp9, single-pass ABR for av1 and
  hardware encoders, bounded overshoot retry, honest `target_size_missed`)
  and `pdf compress --target-size` (lossless-first quality-ladder search,
  `target_size_unreachable` with no output when impossible) join the
  existing image `compress --target-size`; inputs already within budget are
  copied untouched.
- `video concat`: end-to-end concatenation with lossless stream copy by
  default (matching codecs/dimensions enforced via probe) and `--reencode`
  to normalise mixed inputs.
- Verification tooling: `scripts/e2e_sweep.py` drives the whole CLI over a
  seeded synthetic corpus and validates every JSON payload against the
  schemas plus the exit-code/idempotency invariants; the property suite
  gains a randomized `stress` profile
  (`PIXSHIFT_HYPOTHESIS_PROFILE=stress`).

### Changed

- Same-format batch surfaces (`compress`, `strip`, `resize`, `rotate`,
  `crop`, `watermark`) run on a shared bounded process pool (up to 8
  workers, automatic, serial below 4 tasks): 4-4.5x measured on 120-photo
  batches with JSON output order unchanged.
- `pdf compress --target-size` refines between quality-ladder rungs with two
  bounded bisection steps, so the published quality is not limited to the
  ladder's coarse spacing.
- **JSON contract `schema_version` 1.0 -> 1.1** (audit B2): usage rejections
  (bad arguments, conflicting options, plan validation) now exit `2` on both
  channels — previously split between 1 and 2 — while operational failures
  keep exit `1`; and every batch command reports failures as
  `{"input", "output", "error"}` objects with full paths instead of the
  `"name: code"` strings that only `convert` had escaped.
- JSON contract polish under the same 1.1 bump (audit B5): dry-run `preview`
  arrays list every task instead of silently truncating at 50; `manifest` /
  `hash` per-file entries report `size_bytes` (was `bytes`) matching the
  `info` commands; strip previews use `input` (was `file`); `optimize`
  estimates carry a stable `format` token plus a human `label` instead of a
  display string in the machine field.
- `pdf merge` embeds untransformed JPEGs by splicing their original bytes
  (4.3x faster and ~20% smaller on a JPEG-heavy benchmark, zero generation
  loss). EXIF/XMP/comment segments are stripped byte-level so no metadata
  leaks into the PDF; oriented, CMYK, alpha, or `--quality < 95` inputs keep
  the re-encode path.
- `pdf compress` resolves image placements once per page (`get_image_info`)
  instead of re-parsing the content stream per image; 2.7x measured on dense
  pages and growing with image density.
- Terminal UI consistency (audit B4): `resize` / `rotate` / `crop` /
  `watermark` show the shared batch progress bar; `resize` / `rotate` tables
  state how many rows were truncated and end with a `成功 · 跳过 · 失败`
  summary; `crop` / `watermark` list failed files with their error codes
  before the summary panel.

## [1.2.0] - 2026-08-12

### Removed

- **Breaking:** the `watch` command. Long-running directory watching conflicts
  with the deterministic one-shot design; schedule `pixshift convert` with
  cron/launchd instead (ADR-0004).

### Added

- Video pillar (ADR-0005): optional ffmpeg-backed `video info / convert /
  compress / trim / thumbnail / extract-audio / gif` commands with pure,
  unit-testable argv builders, atomic outputs, stable `ffmpeg_missing`
  errors, and `doctor` reporting.
- Opt-in hardware-accelerated video encoding: `video convert` / `video
  compress` accept `--hwaccel videotoolbox|nvenc|qsv` (h264/h265 families),
  translating CRF-style quality onto each backend's knobs; unsupported
  combinations fail with stable `unsupported_hwaccel:*` errors.
- MkDocs documentation site (Material theme) built from `docs/` (now
  covering the whole `video` command group) and published to GitHub Pages at
  <https://changwinde.github.io/pixshift/>, redeployed on
  every push to `main` (`docs.yml` workflow). The site is a Chinese user
  manual — matching the CLI's own output language — organised by pillar
  (images / PDF / video) plus automation, contract, and FAQ chapters, set in
  a monospace typeface. Architecture decision records, the roadmap, and the
  release process stay in the repository and are excluded from the site;
  `docs/COMMANDS.md` is superseded by the per-pillar chapters.
- Probe-driven `optimize` for videos: deterministic codec/bitrate analysis
  (no encoding) recommends `video.convert`, `video.compress`, or an explicit
  `keep` plan with a size estimate; results carry `media_type`.
- `apply` executes `video.convert` / `video.compress` plan steps under the
  image-step safety envelope (collision detection, idempotent skips,
  offline `--dry-run`) and treats `keep` as an explicit skip.
- `resize`: first-class same-format batch resizing (`--size`, `--percent`,
  `--max-size`) with `_resized` derivatives.
- `rotate`: clockwise rotation and mirroring with EXIF orientation normalized
  exactly once, producing `_rotated` derivatives.
- `pdf split`: split a PDF into per-page documents or one sub-range document.

- Forge commit convention (`[scope/op]: title`) documented in CONTRIBUTING and
  enforced via a `commit-msg` pre-commit hook, a CI check on pull-request
  commits, and dependabot commit prefixes.

- AI-native tool surface (ADR-0003): `pixshift tools` catalog with MCP-aligned
  side-effect annotations, and `pixshift apply` to execute `optimize` plans.
- Agent workflow commands: `prep` (bounded convert + privacy strip + hashed
  manifest), `manifest` (inventory with SHA-256 and sensitive-EXIF summary),
  and `hash` (content digests for audits).
- JSON Schema contracts in `docs/schemas/v1/` validated against live command
  output in CI.
- Thin MCP stdio adapter (`python -m pixshift.mcp`) mapping the catalog onto
  the CLI JSON contract.
- `python -m pixshift` module entry point.
- Positioning and governance docs: `GOAL.md`, `AGENTS.md`, ADR-0003, and a
  pre-commit configuration.

### Changed

- README repositioned around the AI-native discover/plan/apply/verify loop,
  with shell-completion instructions.
- Release workflow now publishes to PyPI via trusted publishing behind the
  `pypi` environment gate.
- PDF modules import `pymupdf` under its canonical name, removing the `fitz`
  deprecation warning from CLI output.
- `apply` steps without `--output` follow CLI derivative naming
  (`_compressed`, `_clean`) instead of colliding with the source file.
- Ruff lint scope extended (`W`, `C4`, `PIE`, `RUF`).
- Contributor workflow standardized on `uv sync --frozen --extra dev`.

## [1.1.0] - 2026-08-02

### Added

- A repository-wide policy test that rejects emoji in source, tests, documentation,
  examples, and configuration text.
- Machine-executable `optimize` plans with structured format estimates and sampling metadata.
- Successful CLI integration coverage for image watermarks and every PDF transformation.
- Shared generated-input filtering and idempotent existing-output skips for batch workflows.
- Stable JSON contract version (`schema_version: "1.0"`) for automation and AI clients.
- Shared path-policy, atomic-output, and orientation-normalization primitives.
- Regression coverage for traversal, collisions, failed overwrites, EXIF orientation,
  exact duplicate deletion, target-size bounds, and JSON failure exits.

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

- Removed decorative emoji from CLI help, status messages, tables, summaries, comments,
  and descriptions; status is now expressed with concise text.
- Defaulted conversion/watch quality to `high`, PDF extraction to 150 DPI, and text
  watermark sizing to an image-relative value.
- Bounded large-image optimization trial encodes to a 1600 px sample (4.6× faster in
  the recorded 12 MP benchmark).
- Reduced montage peak memory by decoding one source at a time (58% in the recorded
  24-image benchmark).
- Made PNG/TIFF compression ignore lossy `--quality` values with a structured warning.
- Tightened PDF page-range, page-margin, font-path, and file-argument validation.
- Refactored CLI into modular command registration architecture.
- Unified file collection and output planning in shared core helpers.
- Tightened format support claims to runtime-detected capabilities.
- Preserved transparency for ICO conversion and watermark workflows.
- Normalized destructive-flow safety with confirmation and dry-run behavior.
- Limited automatic conversion workers to eight by default to avoid decoder memory pressure.
- Replaced quadratic perceptual-hash clustering with multi-index hashing.
- Simplified root help while keeping detailed per-command help.
- Switched CI/release dependency management to locked `uv` workflows and pinned actions.
- Raised enforced test coverage gate to `60%`.

### Fixed

- Removed sensitive device and personal fields stored in nested EXIF directories during
  default privacy cleanup while preserving metadata outside the selected categories.
- Rejected multi-frame inputs in still-image-only transformations and analyzers instead
  of silently replacing animations with their first frame.
- Excluded animations from perceptual deduplication while retaining byte-identical
  animation detection and reporting the skipped analysis count.
- Detected indexed transparency consistently and flattened it onto the configured
  background for opaque outputs.
- Required exact pixel and alpha equality for a perfect comparison rating.
- Kept empty deduplication analysis payloads consistent with the documented JSON schema.
- Prevented recursive/repeated workflows from consuming their own outputs or watermark assets.
- Made the documented "skip existing output" behavior idempotent instead of a failed batch.
- Prevented invalid or out-of-range PDF page selections from silently succeeding with no output.
- Rejected misleading comparisons across different aspect ratios and invalid/conflicting
  resize expressions; tiny percentage resizes now retain at least one pixel per dimension.
- Removed Pillow deprecation usage in compare engine data access.
- Prevented output path traversal, flattened-name collisions, recursive watch loops,
  recursive watch same-name overwrites, stale EXIF orientation, and partial overwrite
  corruption.
- Made target-size compression fail when the requested bound cannot be reached.
- Restricted automatic duplicate deletion to freshly revalidated byte-identical files.
- Made failed JSON operations return non-zero status consistently.
- Made Click parameter-validation failures machine-readable in `--json` mode.
- Distinguished required and optional capabilities in `doctor` exit semantics.
- Rejected montage extensions that do not match its PNG/JPEG/WebP encoders.
- Synchronized the runtime version with installed package metadata.
