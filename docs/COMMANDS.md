# PixShift Command Reference

This page is a concise reference for all commands.

## Core Workflows

### `convert`

Convert image formats in batch.

```bash
pixshift convert INPUTS... -t webp [-o OUT_DIR] [-r] [--json]
```

### `compress`

Compress images without changing format.

```bash
pixshift compress INPUTS... [-p medium] [-o OUT_DIR] [-r] [--json]
```

### `strip`

Remove metadata for privacy or cleanup.

```bash
pixshift strip INPUTS... [--mode privacy] [-o OUT_DIR] [-r] [--json]
```

### `dedup`

Analyze or delete duplicate/similar images.

```bash
pixshift dedup INPUTS... [-r] [--delete] [--dry-run] [--yes] [--json]
```

## Advanced Workflows

### `compare`

Compare quality of two images.

```bash
pixshift compare A.jpg B.jpg [--json]
```

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

### `watermark image`

Add image/logo watermark to one or many images.

```bash
pixshift watermark image INPUTS... --watermark logo.png [-r] [--json]
```

### `montage`

Build a grid montage from multiple images.

```bash
pixshift montage INPUTS... -o board.png [--cols 4] [-r] [--json]
```

### `optimize`

Analyze images and get format recommendations.

```bash
pixshift optimize INPUTS... [-r] [--json]
```

### `watch`

Watch a directory and auto-convert new files.

```bash
pixshift watch ./incoming -t webp
pixshift watch ./incoming --once --json
```

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

