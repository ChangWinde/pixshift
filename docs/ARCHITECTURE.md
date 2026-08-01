# PixShift Architecture

PixShift is a local-first CLI. Click commands translate user intent, operation
wrappers provide a narrow service boundary, engines perform image/PDF work, and
shared core modules enforce invariants that must not vary by command.

## Runtime Layers

```text
CLI commands
  ├─ validate options and build complete task plans
  ├─ Rich presenter (human output)
  └─ JSON presenter (schema_version 1.0)
          │
          ▼
ops wrappers
          │
          ▼
image/PDF engines
          │
          ▼
core policy
  ├─ files.py     collection, root containment, collision checks, atomic writes
  ├─ metadata.py  visual orientation and canonical EXIF handling
  ├─ errors.py    stable policy error codes
  └─ models.py    shared batch summaries
```

Commands remain adapters: they may select options and presentation, but must not
reimplement path, deletion, or metadata safety decisions.

## Product Surface

The primary workflows are `convert`, `compress`, `strip`, and `dedup`. Focused
utilities (`compare`, `crop`, `watermark`, `montage`, `optimize`, `watch`, and the
`pdf` group) stay independent so users do not need to configure a large pipeline
for a single operation. Root help intentionally stays compact; detailed options
live under each command.

## Safety Invariants

- A full batch is planned and checked for destination collisions before writing.
- A generated path stays below the explicitly selected output root.
- Encoders write to a same-directory temporary file and atomically replace only
  after successful completion.
- Pixel-changing operations normalize EXIF Orientation exactly once and remove the
  consumed tag.
- Similar-image groups are advisory. Automatic deletion is limited to byte-identical
  files whose size and SHA-256 digest are revalidated immediately before removal.
- An impossible target-size request fails without leaving a misleading output.
- JSON documents with `ok: false` terminate with a non-zero exit code.

The accepted design and alternatives are recorded in
[ADR-0001](adr/0001-safe-operation-boundaries.md).

## Automation and AI Clients

AI and scripts use the same deterministic CLI contract as humans. Every JSON
document contains `schema_version`, `command`, and `ok`; paths and numeric sizes
are explicit, Click parsing failures use the same JSON channel, and dry-run modes
expose bounded previews. No model call sits in the media-processing hot path, so
local performance and reproducibility do not depend on network availability.

## Performance Model

- Single-file conversion stays in-process to avoid process startup overhead.
- Batch conversion uses at most eight workers by default to bound decoder memory;
  callers can override this with `--jobs`.
- Perceptual duplicate search uses multi-index hashing plus union-find instead of
  comparing every pair. Threshold zero uses direct hash grouping.
- Exact-file SHA-256 is computed only for equal-size candidates.
- Target-size compression encodes in memory and atomically writes the exact tested
  payload, avoiding a second unverified encode.

## Quality Gates

CI runs Ruff lint/format checks, mypy, the full pytest suite, a 60% coverage floor,
and package build/metadata validation. Dependencies are resolved from `uv.lock`,
and third-party GitHub Actions are pinned to immutable commit SHAs.
