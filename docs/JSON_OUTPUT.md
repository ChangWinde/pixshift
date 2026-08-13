# JSON Output Contract

PixShift provides stable JSON output for automation with the `--json` flag.

Formal JSON Schema files for the envelope and command payloads live in
`docs/schemas/v1/` and are validated against live command output in CI.
Fields are additive under a given `schema_version`; removing or retyping a
documented field requires a version bump. The current version is `"1.1"`:
it retyped the batch commands' `errors` arrays from `"name: code"` strings
to `{"input", "output", "error"}` objects with full input paths.

## Exit Codes

- `0` — success, including idempotent skips and `keep` plans.
- `1` — operational failure: work was attempted and at least one item failed
  (per-item details in the payload's `errors` / `results` / `steps`).
- `2` — usage rejection: the invocation was refused before any output was
  written — Click parse errors, argument semantics (`conflicting_options`,
  `invalid_*`, `nothing_to_do`), and batch plan validation (filename affixes,
  output collisions). JSON mode still emits
  `{"command", "ok": false, "error", "detail"?}` on stdout.

## Failure Arrays

Batch commands (`convert`, `compress`, `strip`, `resize`, `rotate`, `crop`,
`watermark *`) report failed items in `errors` as objects:
`{"input": <full path>, "output": <planned path or "">, "error": <code>}`.

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
- `pixshift resize ... --json`
- `pixshift rotate ... --json`
- `pixshift watermark text ... --json`
- `pixshift watermark image ... --json`
- `pixshift montage ... --json`
- `pixshift optimize ... --json`
- `pixshift pdf merge ... --json`
- `pixshift pdf extract ... --json`
- `pixshift pdf split ... --json`
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
- `results[*].media_type` (`image` or `video`)
- `results[*].recommended_format`
- `results[*].recommended_reason`
- `results[*].analysis` (images: dimensions, sampling basis, alpha and
  classification reason; videos: codec, duration, dimensions, bits per pixel)
- `results[*].estimates` (format, estimated bytes, ratio and quality properties)
- `results[*].plan.command` (`convert`, `compress`, `strip`, `video.convert`,
  `video.compress`, or `keep`; empty object on per-file errors)
- `results[*].plan.arguments` (structured CLI option values)

Video analysis is probe-driven and deterministic — nothing is encoded. A
`keep` plan states that re-encoding would not pay off; `apply` treats it as an
explicit skip.

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
- Video steps (`video.convert`, `video.compress`) report `ffmpeg_missing`
  when ffmpeg is absent; `keep` steps count as `skipped` with detail
  `plan_keep`.

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

## Transform Command Payloads

### `resize --json`

- `total`, `success`, `failed`, `skipped`, `ignored_generated`
- `quality`, `input_bytes`, `output_bytes`, `duration_sec`
- `errors` (array)
- Dry-run mode returns `mode: "dry_run"` with `pending` and a bounded `preview`.

### `rotate --json`

- `total`, `success`, `failed`, `skipped`, `ignored_generated`
- `degrees`, `flip`, `duration_sec`
- `errors` (array)

### `pdf split --json`

- `mode` (`each` or `single`)
- `total_pages`, `requested_pages`, `written_files`, `skipped_existing`
- `input_bytes`, `output_bytes`, `duration_sec`
