# PixShift Command Reference

This page is a concise reference for all commands.

## Media Semantics

Pixel-changing commands, `compare`, `optimize`, and PDF image merge currently accept
still images only. A multi-frame GIF, APNG, WebP, or TIFF fails with
`animated_input_not_supported` before an output is replaced. The exact-copy path of
`compress --preset lossless` may still copy an already lossy animated file byte-for-byte
because that path does not decode or discard frames. Use `info` to inspect `frame_count`
before building an automated workflow.

## Core Workflows

### `convert`

Convert image formats in batch.

```bash
pixshift convert INPUTS... -t webp [-o OUT_DIR] [-r] [--json]
```

The default `high` quality preset balances visual quality, output size, and encoding
speed. Use `-q max` explicitly for archival-oriented encoding. Directory discovery
ignores files already in the target format; an explicit file argument is always honored.

Animated inputs (GIF, APNG, animated WebP) keep their animation — frames,
per-frame timing, loop count, and transparency — when the target format can
animate (`webp`, `gif`, `png`). Targets that cannot (jpg, heic, avif, ...)
fail with a stable `animated_input_not_supported` error rather than silently
dropping frames. Resize options apply to every frame.

### `compress`

Compress images without changing format.

```bash
pixshift compress INPUTS... [-p medium] [-o OUT_DIR] [-r] [--json]
```

`--quality` controls lossy codecs. PNG and TIFF remain lossless and use the selected
preset's compression settings; JSON reports a warning when `--quality` is ignored for
those formats. `--quality` and `--target-size` are mutually exclusive.

### `strip`

Remove metadata for privacy or cleanup.

```bash
pixshift strip INPUTS... [--mode privacy] [-o OUT_DIR] [-r] [--json]
```

The default `privacy` mode removes GPS, device, and personal fields from both top-level
EXIF and nested EXIF directories while preserving unrelated time and color metadata.
Use `--mode all` only when every EXIF field must be removed.

### `dedup`

Analyze similar images and optionally delete byte-identical duplicates.

```bash
pixshift dedup INPUTS... [-r] [--delete] [--dry-run] [--yes] [--json]
```

`--delete` never removes a file based only on perceptual similarity. Candidates
must be byte-identical and are revalidated immediately before deletion.
Animations are excluded from perceptual grouping because comparing only their first
frame is misleading. Byte-identical animations remain eligible for safe exact deduplication.

## Advanced Workflows

### `compare`

Compare quality of two images.

```bash
pixshift compare A.jpg B.jpg [--json]
```

Images with the same aspect ratio may be normalized to a common size. Materially
different aspect ratios fail instead of producing misleading similarity metrics. The
`完美` rating requires exact pixel and transparency equality; luminance SSIM alone is
not treated as proof of equality.

### `crop`

Crop images by explicit box, aspect ratio, or auto trim.

```bash
pixshift crop INPUTS... (--crop L,T,R,B | --aspect 16:9 | --trim) [-r] [--json]
```

### `watermark text`

Add text watermark to one or many images.

```bash
pixshift watermark text INPUTS... --text "demo" [-r] [--json]
```

Text size defaults to an image-relative value. Pass `--font-size` for a fixed size.

### `watermark image`

Add image/logo watermark to one or many images.

```bash
pixshift watermark image INPUTS... --watermark logo.png [-r] [--json]
```

### `montage`

Build a grid montage from multiple images.
Output must use `.png`, `.jpg`/`.jpeg`, or `.webp`.

```bash
pixshift montage INPUTS... -o board.png [--cols 4] [-r] [--json]
```

### `optimize`

Analyze images and videos and get format recommendations.

```bash
pixshift optimize INPUTS... [-r] [--json]
```

JSON includes bounded format-size estimates, sampling metadata, and a `plan` object with
a command plus structured arguments. Large images are sampled to keep analysis fast.

Video files are analysed from ffprobe metadata only (no encoding): legacy codecs get a
`video.convert` plan, wasteful bitrates a same-family `video.compress` plan, and
already-efficient files an explicit `keep` plan. Requires ffmpeg; without it each video
entry carries a stable `ffmpeg_missing` error.

Animated images classify as `animation`: GIF/APNG get an executable
`convert -t webp` plan (animation preserved, typically 30-60% smaller), an
already-animated WebP gets an explicit `keep` plan.

### `resize`

Resize images in batch while keeping their format; outputs `_resized` derivatives.

```bash
pixshift resize INPUTS... (--size WxH | --percent P | --max-size N) \
  [-o OUT_DIR] [-q high] [-r] [--overwrite] [--dry-run] [--json]
```

Exactly one sizing mode is required. `--max-size` bounds the longest side and
never enlarges. Same-format re-encode applies the selected quality preset to
lossy formats. Animated GIF/APNG/WebP inputs are resized frame by frame with
timing and loop preserved.

### `rotate`

Rotate clockwise or mirror still images; outputs `_rotated` derivatives.

```bash
pixshift rotate INPUTS... [--degrees 90|180|270] [--flip horizontal|vertical] \
  [-o OUT_DIR] [-r] [--overwrite] [--json]
```

EXIF orientation is normalized exactly once before the transform, so results
match what viewers display. Animated inputs are rejected.

## System Commands

### `info`

Inspect image metadata and properties.

```bash
pixshift info FILES... [--exif] [--json]
```

### `formats`

Show runtime-detected format capabilities.

```bash
pixshift formats [--json]
```

### `doctor`

Check runtime dependencies and environment status.

```bash
pixshift doctor [--json]
```

## PDF Commands

```bash
pixshift pdf merge INPUTS... -o out.pdf [--json]
pixshift pdf extract input.pdf -o out_dir [--json]
pixshift pdf compress input.pdf [-p preset | --target-size 2MB] [--max-dpi N] \
  [-o out.pdf] [--json]
pixshift pdf concat INPUTS... -o out.pdf [--json]
pixshift pdf info input.pdf [--pages] [--json]
```

`pdf merge` converts images into a PDF; `pdf concat` joins existing PDF documents.
Page extraction defaults to 150 DPI. Pass `--dpi 300` when print-level raster output is
more important than speed and file size.

`pdf compress --target-size` fits the document under a byte budget at the best
quality: it tries lossless structure optimisation first, then walks a
descending image-quality ladder and publishes the first candidate that fits
(bounded attempts). An input already within budget is copied untouched; an
unreachable target fails with `target_size_unreachable` and leaves no output.
Mutually exclusive with `-p`/`--image-quality`.

## Video Commands

All video commands need ffmpeg/ffprobe on the PATH (optional, reported by
`doctor`); without them each command fails with a stable `ffmpeg_missing`
error. Outputs are written atomically and existing outputs are idempotent
skips unless `--overwrite` is set.

```bash
pixshift video info FILES... [--json]
pixshift video convert INPUTS... [-t mp4|webm|mkv|mov] [--codec h264|h265|vp9|av1] \
  [--hwaccel videotoolbox|nvenc|qsv] [-o OUT_DIR] [-r] [--overwrite] [--json]
pixshift video compress INPUTS... [-p web|archive|tiny] [--codec h264|h265|vp9|av1] \
  [--crf N | --target-size 25MB] [--hwaccel videotoolbox|nvenc|qsv] \
  [-o OUT_DIR] [-r] [--overwrite] [--json]
pixshift video concat CLIPS... -o joined.mp4 [--reencode] [--overwrite] [--json]
pixshift video trim SOURCE --start TS [--end TS | --duration SEC] [--reencode] \
  [-o OUT_FILE] [--overwrite] [--json]
pixshift video thumbnail INPUTS... [--at 25% | --at TS] [-t jpg|png|webp] \
  [-o OUT_DIR] [-r] [--overwrite] [--json]
pixshift video extract-audio INPUTS... [-t mp3|aac|m4a|opus|flac|wav] \
  [-o OUT_DIR] [-r] [--overwrite] [--json]
pixshift video gif SOURCE [--start TS] [--duration SEC] [--fps N] [--width N] \
  [-o OUT_FILE] [--overwrite] [--json]
```

`convert` picks the container's default codec (mp4/mov: h264, mkv: h265,
webm: vp9) unless `--codec` overrides it. `compress` writes `_compressed`
derivatives in the codec's native container. `trim` stream-copies at keyframes
by default; `--reencode` cuts precisely at the cost of a re-encode. `thumbnail`
accepts a percentage of the probed duration or an absolute timecode. `gif`
uses a palette filter graph for quality output.

`compress --target-size` answers the most common ask — *stay under this size
with the best possible quality*: the byte budget converts into a video bitrate
(audio and container overhead reserved) and encodes in two passes for the
software h264/h265/vp9 paths (single-pass ABR for av1 and hardware encoders).
Inputs already within budget are copied untouched; one bounded retry absorbs
rate-control overshoot, and a second miss fails honestly with
`target_size_missed` and no output. Mutually exclusive with `-p`/`--crf`.

`concat` joins clips end to end. By default it stream-copies (lossless and
instant) and requires matching codecs/dimensions — mixed inputs fail with
`concat_requires_matching_streams`; pass `--reencode` to normalise everything
to h264 instead.

`--hwaccel` opts in to the platform's hardware encoder (h264/h265 families
only): `videotoolbox` on macOS, `nvenc` on NVIDIA GPUs, `qsv` on Intel.
The CRF-style quality target is translated onto each backend's own knobs
(`-cq`, `-global_quality`, `-q:v`). Hardware encoders trade some quality per
bit for large speed gains; verify availability with `ffmpeg -encoders`.
Plans emitted by `optimize` never include `hwaccel`, so they stay portable
across hosts.

## Agent Tools

### `tools`

List the agent-facing tool catalog with side-effect annotations.

```bash
pixshift tools [--json]
```

Every entry carries `readOnlyHint`, `destructiveHint`, `idempotentHint`, and
`openWorldHint` (always `false` for local tools).

### `apply`

Execute machine plans produced by `optimize` (or written by hand).

```bash
pixshift apply --plan plan.json [-o OUT_DIR] [--overwrite] [--dry-run] [--json]
pixshift optimize ./photos --json | pixshift apply --plan - --json
```

Supported plan commands: `convert`, `compress`, `strip`, `video.convert`,
`video.compress`, and `keep` (an explicit no-op for already-efficient files).
Existing outputs are idempotent skips unless `--overwrite` is set. Without `-o`,
outputs follow the CLI naming conventions next to the source: `convert` swaps
the extension, `compress` appends `_compressed`, and `strip` appends `_clean`;
video steps mirror the `video` command naming. Video steps validate their
vocabulary and plan outputs under `--dry-run` even without ffmpeg; real
execution reports `ffmpeg_missing` when the optional dependency is absent.

### `prep`

Prepare delivery-ready assets in one shot: bounded resize, format conversion,
privacy metadata strip, and a hashed manifest.

```bash
pixshift prep INPUTS... -o OUT_DIR [--max-size 2048] [-t webp] [-q high] \
  [--keep-metadata] [-r] [--overwrite] [--dry-run] [--json]
```

### `manifest`

Inventory media files: dimensions, format, alpha, frame count, sensitive EXIF
keys, and SHA-256 content digests.

```bash
pixshift manifest INPUTS... [-r] [--json]
```

### `hash`

Compute content hashes for audits (media files by default).

```bash
pixshift hash INPUTS... [-r] [--algorithm sha256] [--all-files] [--json]
```

### `pdf split`

Split a PDF into standalone PDFs.

```bash
pixshift pdf split report.pdf -o ./pages/ [--pages '1-5,8'] [--single] [--overwrite] [--json]
```

Default writes one PDF per selected page (`{stem}_page_0001.pdf`); `--single`
writes one document containing the selected pages.

## Repeat Runs

Batch commands skip existing outputs unless `--overwrite` is set. Files discovered in a
generated output subtree, prior paired derivatives such as `photo_compressed.jpg`, and an
operation's own aggregate output or watermark asset are not fed back into the operation.
Explicit file inputs remain authoritative. JSON reports `skipped` and
`ignored_generated` separately.
