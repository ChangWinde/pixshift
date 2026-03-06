# PixShift Architecture Draft

This document defines the target architecture for PixShift and a staged migration
path that keeps the CLI stable while improving code quality and maintainability.

## Target Design Goals

- High-confidence behavior for daily batch workflows.
- Clear command model: core workflows first, advanced tools second.
- Reusable operation primitives across commands.
- Consistent output model for both humans and scripts.

## Target Command Layout

```text
pixshift
├─ convert
├─ compress
├─ strip
├─ dedup
├─ compare
├─ crop
├─ watermark
├─ montage
├─ optimize
├─ watch
├─ info
├─ formats
├─ doctor
└─ pdf
   ├─ merge
   ├─ extract
   ├─ compress
   ├─ concat
   └─ info
```

Advanced commands now available as first-class CLI surfaces:
`compare`, `crop`, `watermark`, `montage`, `optimize`, `watch`.

## Target Repository Structure

```text
pixshift/
├─ core/
│  ├─ errors.py           # Shared domain errors
│  ├─ files.py            # Input scanning and output planning
│  ├─ models.py           # Common result models and typed contracts
│  ├─ parallel.py         # Shared batch/parallel runner
│  └─ metadata.py         # EXIF/ICC/orientation helpers
├─ ops/
│  ├─ convert.py
│  ├─ compress.py
│  ├─ strip.py
│  ├─ dedup.py
│  └─ pdf.py
├─ presenters/
│  ├─ rich_report.py      # Rich tables/panels
│  └─ json_report.py      # Stable machine-readable output
├─ cli/
│  ├─ app.py              # Click root group and registration
│  └─ commands/
│     ├─ convert_cmd.py
│     ├─ compress_cmd.py
│     ├─ strip_cmd.py
│     ├─ dedup_cmd.py
│     └─ pdf_cmd.py
└─ legacy_engines/        # Transitional location during migration
```

## Transitional Strategy

1. Keep public CLI names stable.
2. Move shared logic into `core/` first.
3. Replace direct engine imports in CLI with `ops/` services.
4. Split one command at a time from monolithic `cli.py`.
5. Preserve behavior with fixture-based regression tests.

Current progress:
- `core/files.py` is active and used by conversion + derivative workflows.
- `core/models.py` provides shared typed operation summary.
- High-frequency commands are extracted to `commands/workflow_commands.py`.
- `ops/` wrappers are active for convert/compress/strip/dedup/pdf paths.

## Quality Guardrails

- Every command has typed option parsing and typed result objects.
- Shared file/path planning logic is centralized (no duplicated collectors).
- Every destructive action supports dry-run or confirmation.
- Command output has both human mode and JSON mode.
- Add regression fixtures for EXIF/orientation/alpha/PDF edge cases.
