# Phase 1 Refactor Checklist

Scope: deliver immediate product value while keeping risk low.

## Execution Objective

Build PixShift into a high-frequency daily CLI with:
- stable command UX,
- clear internal layering,
- predictable and test-backed behavior.

## A) Product Surface

- [x] Add high-frequency commands to top-level CLI: `compress`, `strip`, `dedup`.
- [x] Rewrite README homepage around daily workflows.
- [x] Publish architecture draft and migration direction.
- [x] Add stable command output mode: `--json` (all core commands).

## B) Correctness

- [x] Fix output path planning to correctly honor directory structure vs flatten.
- [x] Tighten claimed format support to match real runtime capabilities.
- [x] Add explicit validation for user inputs (quality ranges, color tuples, etc.).

## C) Structure

- [x] Introduce `core/files.py` and migrate all file collection/output planning.
- [x] Introduce `core/models.py` for shared batch result types.
- [x] Create `ops/` wrappers for `convert/compress/strip/dedup/pdf`.
- [x] Start splitting `cli.py` into `cli/commands/` one command at a time.

## D) Quality and Safety

- [x] Add fixture tests for `convert` (EXIF orientation, alpha, ICC preservation).
- [x] Add fixture tests for `strip` (mode behavior and field removal).
- [x] Add fixture tests for `dedup` (hash threshold and delete behavior).
- [x] Add fixture tests for `pdf` (merge/extract/compress smoke coverage).
- [x] Add CI job for lint + tests on Python 3.8+.
- [x] Add test coverage gate in CI for regression control.

## E) UX Consistency

- [x] Normalize flags across commands (`-o`, `-r`, `--overwrite`, `--dry-run`).
- [x] Unify command summary panels (same success/failure/size/time sections).
- [x] Ensure all destructive flows require explicit confirmation.
