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

Analyze images and get format recommendations.

```bash
pixshift optimize INPUTS... [-r] [--json]
```

JSON includes bounded format-size estimates, sampling metadata, and a `plan` object with
a command plus structured arguments. Large images are sampled to keep analysis fast.

### `resize`

Resize images in batch while keeping their format; outputs `_resized` derivatives.

```bash
pixshift resize INPUTS... (--size WxH | --percent P | --max-size N) \
  [-o OUT_DIR] [-q high] [-r] [--overwrite] [--dry-run] [--json]
```

Exactly one sizing mode is required. `--max-size` bounds the longest side and
never enlarges. Same-format re-encode applies the selected quality preset to
lossy formats.

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
pixshift pdf compress input.pdf [-o out.pdf] [--json]
pixshift pdf concat INPUTS... -o out.pdf [--json]
pixshift pdf info input.pdf [--pages] [--json]
```

`pdf merge` converts images into a PDF; `pdf concat` joins existing PDF documents.
Page extraction defaults to 150 DPI. Pass `--dpi 300` when print-level raster output is
more important than speed and file size.

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

Supported plan commands: `convert`, `compress`, `strip`. Existing outputs are
idempotent skips unless `--overwrite` is set. Without `-o`, outputs follow the
CLI naming conventions next to the source: `convert` swaps the extension,
`compress` appends `_compressed`, and `strip` appends `_clean`.

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
