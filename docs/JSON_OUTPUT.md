# JSON Output Contract

PixShift provides stable JSON output for automation with the `--json` flag.

Formal JSON Schema files for the envelope and command payloads live in
`docs/schemas/v1/` and are validated against live command output in CI.
Fields are additive under `schema_version` `"1.0"`; removing or retyping a
documented field requires a version bump.

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
- `pixshift tools --json`
- `pixshift apply --plan ... --json`
- `pixshift prep ... --json`
- `pixshift manifest ... --json`
- `pixshift hash ... --json`

## Common Fields

- `schema_version`: machine-contract version; currently `"1.0"`
- `command`: command identifier, e.g. `compress`, `pdf.info`
- `ok`: boolean success state
- `error`: error string when `ok` is false (if available)

Still-image-only operations use the stable error
`animated_input_not_supported` for multi-frame inputs. They validate this condition
before replacing an output file.

Batch workflow payloads additionally use integer `skipped` and
`ignored_generated` counts. Deduplication's operation-specific `skipped` field remains
an array of safety reasons.

## Workflow Command Payloads

### `convert --json`

- `total`, `success`, `failed`
- `output_format`, `quality`
- `input_bytes`, `output_bytes`
- `duration_sec`
- `errors` (array)
- `skipped`, `ignored_generated`

### `compress --json`

- `total`, `success`, `failed`
- `input_bytes`, `output_bytes`
- `duration_sec`
- `errors` (array)
- `skipped`, `ignored_generated`
- `warnings` (array; for example `quality_ignored_for_lossless`)

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
- `skipped_invalid` (files excluded from perceptual analysis, including animations)
- `preview` (array of groups, truncated)

Perceptual similarity is advisory. `deletable_files` and `recoverable_bytes` count
only byte-identical files verified with SHA-256. Exact duplicate detection still covers
files excluded from perceptual analysis.

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
- `files` (array of per-file metadata)
- Each file includes `frame_count` and `has_alpha`; indexed transparency counts as alpha.
- EXIF is included only when `--exif` is set.

### `formats --json`

- `input_extensions` (array)
- `output_formats` (array)
- `features.heif`
- `features.avif_encode`
- `defaults` (canonical common workflow defaults for clients)

### `doctor --json`

- `all_ready` (boolean)
- `checks` (array with `name`, `status`, `ok`, `required`)
- Missing optional encoders remain visible in `checks` but do not make the command fail.

## Advanced Command Payloads

### `compare --json`

- `image_a`, `image_b`
- `mse`, `psnr`, `ssim`
- `quality_rating`, `quality_detail`
- `comparison_size`, `resized_for_comparison`

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
- `results[*].analysis` (dimensions, sampling basis, alpha and classification reason)
- `results[*].estimates` (format, estimated bytes, ratio and quality properties)
- `results[*].plan.command`
- `results[*].plan.arguments` (structured CLI option values)

### `watch --once --json`

- `mode: "once"`
- `total`, `success`, `failed`, `skipped`
- `output_format`, `quality`
- `errors` (array)

## PDF Command Payloads

### `pdf merge --json`

- `input_count`, `output`, `page_count`
- `input_bytes`, `output_bytes`
- `duration_sec`

### `pdf extract --json`

- `input`, `output_dir`
- `total_pages`, `exported_pages`
- `requested_pages`, `skipped_existing`, `output_format`, `dpi`
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

## Agent Command Payloads

### `tools --json`

- `total`
- `tools` (array of `name`, `description`, `when_to_use`, `input_summary`,
  `annotations` with `readOnlyHint` / `destructiveHint` / `idempotentHint` /
  `openWorldHint`)

### `apply --json`

- `total`, `applied`, `skipped`, `failed`, `dry_run`
- `steps` (array of `input`, `plan_command`, `arguments`, `output`, `ok`,
  `skipped`, `error`, `detail`)
- Accepted plan documents: an `optimize --json` payload, a single plan object,
  a `{"plans": [...]}` wrapper, or a JSON array of plan objects.

### `prep --json`

- `total`, `success`, `skipped`, `failed`, `ignored_generated`, `output_dir`, `dry_run`
- `items` (array of `input`, `output`, `ok`, `skipped`, `input_bytes`,
  `output_bytes`, `sha256`, `width`, `height`, `error`)

### `manifest --json`

- `total`
- `files` (array of `path`, `sha256`, `bytes`, `format`, `width`, `height`,
  `mode`, `has_alpha`, `frame_count`, `sensitive_exif_keys`, `error`)

### `hash --json`

- `total`, `algorithm`
- `files` (array of `path`, `algorithm`, `digest`, `bytes`, `error`)
