# JSON Output Contract

PixShift provides stable JSON output for automation with the `--json` flag.

## Supported Commands

- `pixshift compress ... --json`
- `pixshift strip ... --json`
- `pixshift dedup ... --json`
- `pixshift convert ... --json`
- `pixshift info ... --json`
- `pixshift formats --json`
- `pixshift doctor --json`
- `pixshift compare ... --json`
- `pixshift crop ... --json`
- `pixshift watermark text ... --json`
- `pixshift watermark image ... --json`
- `pixshift montage ... --json`
- `pixshift optimize ... --json`
- `pixshift watch ... --once --json`
- `pixshift pdf merge ... --json`
- `pixshift pdf extract ... --json`
- `pixshift pdf compress ... --json`
- `pixshift pdf concat ... --json`
- `pixshift pdf info ... --json`

## Common Fields

- `schema_version`: machine-contract version; currently `"1.0"`
- `command`: command identifier, e.g. `compress`, `pdf.info`
- `ok`: boolean success state
- `error`: error string when `ok` is false (if available)

## Workflow Command Payloads

### `convert --json`

- `total`, `success`, `failed`
- `output_format`, `quality`
- `input_bytes`, `output_bytes`
- `duration_sec`
- `errors` (array)

### `compress --json`

- `total`, `success`, `failed`
- `input_bytes`, `output_bytes`
- `duration_sec`
- `errors` (array)

### `strip --json`

- `total`, `success`, `failed`
- `fields_removed`
- `input_bytes`, `output_bytes`
- `duration_sec`
- `errors` (array)

### `dedup --json`

Analyze mode (`--delete` not set):
- `mode: "analyze"`
- `total_files`, `duplicate_groups`, `duplicate_files`
- `deletable_files`, `recoverable_bytes`
- `preview` (array of groups, truncated)

Perceptual similarity is advisory. `deletable_files` and `recoverable_bytes` count
only byte-identical files verified with SHA-256.

Delete mode (`--delete` set):
- `mode: "delete"`
- `deleted`, `kept`, `skipped`
- `errors` (array)
- A candidate changed after analysis is reported in `skipped` and is not deleted.
- In `--json` mode, use `--yes` with `--delete` to avoid interactive prompts.

Delete dry-run mode (`--delete --dry-run`):
- `mode: "delete_dry_run"`
- `would_delete`, `keep`

## System Command Payloads

### `info --json`

- `total`
- `files` (array of per-file metadata; includes EXIF only when `--exif` is set)

### `formats --json`

- `input_extensions` (array)
- `output_formats` (array)
- `features.heif`
- `features.avif_encode`

### `doctor --json`

- `all_ready` (boolean)
- `checks` (array with `name`, `status`, `ok`, `required`)
- Missing optional encoders remain visible in `checks` but do not make the command fail.

## Advanced Command Payloads

### `compare --json`

- `image_a`, `image_b`
- `mse`, `psnr`, `ssim`
- `quality_rating`, `quality_detail`

### `crop --json`

- `total`, `success`, `failed`
- `input_bytes`, `output_bytes`
- `errors` (array)
- dry-run: `mode: "dry_run"`, `preview`

### `watermark text|image --json`

- `total`, `success`, `failed`
- `input_bytes`, `output_bytes`
- `errors` (array)
- dry-run: `mode: "dry_run"`, `preview`

### `montage --json`

- `total_images`, `grid_size`, `canvas_size`
- `output`, `output_bytes`

### `optimize --json`

- `total`
- `results[*].input`
- `results[*].recommended_format`
- `results[*].recommended_reason`

### `watch --once --json`

- `mode: "once"`
- `total`, `success`, `failed`
- `errors` (array)

## PDF Command Payloads

### `pdf merge --json`

- `input_count`, `output`, `page_count`
- `input_bytes`, `output_bytes`
- `duration_sec`

### `pdf extract --json`

- `input`, `output_dir`
- `total_pages`, `exported_pages`
- `input_bytes`, `output_bytes`
- `duration_sec`

### `pdf compress --json`

- `input`, `output`, `page_count`
- `input_bytes`, `output_bytes`
- `duration_sec`

### `pdf concat --json`

- `input_count`, `output`, `page_count`
- `input_bytes`, `output_bytes`
- `duration_sec`

### `pdf info --json`

- `path`, `size_bytes`, `page_count`
- `encrypted`, `pdf_version`, `image_count`
- `metadata` (object)
- `pages` (array when `--pages` is set, otherwise `null`)

## Stability Note

Field names listed in this document are intended to be stable for scripts.
Future versions may add new fields, but existing documented fields should
remain backward compatible.

## Exit Code Semantics (JSON Mode)

- `0`: successful command execution (`ok: true`)
- `1`: command-level failure (`ok: false`)

Notes:
- "No files found" cases that are non-destructive and expected return `ok: true`
  with exit code `0`.
- Validation failures (including Click's missing parameter, invalid value, and
  unknown option errors) return versioned JSON with `ok: false` and a non-zero
  exit code whenever `--json` is present.
