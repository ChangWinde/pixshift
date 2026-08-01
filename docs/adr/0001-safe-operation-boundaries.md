# ADR-0001: Centralize safe operation boundaries

## Status

Accepted

## Context

PixShift currently implements path construction, metadata handling, output writes,
batch validation, and destructive duplicate handling in multiple engines. The
duplication has produced reachable failures: output traversal, destination
collisions, stale EXIF orientation, misleading target-size success, and deletion
of perceptually similar but different files.

## Driving Factors

- Existing CLI names and documented JSON fields should remain compatible.
- A batch must fail before writing when destinations collide or escape their root.
- Output replacement must be atomic on the destination filesystem.
- Automatic deletion must require a freshly verified byte-identical source.
- AI or automation callers need one deterministic, typed machine contract.
- Image processing startup and per-file execution must remain local and fast.

## Candidates

### Option A: Patch each engine independently

- Pros: smallest local diffs; minimal initial refactoring.
- Cons: repeats security policy; keeps inconsistent error semantics; future
  operations can bypass fixes accidentally.

### Option B: Compatible CLI over shared safety primitives

- Pros: one enforcement point for paths, writes, orientation, and destructive
  actions; preserves command names; provides a stable base for typed plans.
- Cons: touches several engines and requires cross-command regression coverage.

### Option C: Replace commands with a new plan/run pipeline immediately

- Pros: smallest long-term product surface and strongest composition model.
- Cons: breaks public CLI workflows and is too large for a corrective patch.

## Decision

Chosen: Option B. Existing commands remain adapters. Shared `core` modules own
path and output policy, orientation normalization, and common result contracts.
Engines retain image/PDF algorithms. Option C remains a future versioned product
change after the compatibility layer is proven.

The canonical machine boundary is UTF-8 JSON with `command`, `ok`, and a process
exit code where `ok: false` always exits non-zero. Additive fields remain allowed.

## Interfaces

- `OutputPolicy`: validates filename components, root containment, destination
  uniqueness, and atomic replacement.
- `MetadataPolicy`: normalizes visual orientation and removes stale Orientation.
- `DeletionCandidate`: binds keep path, duplicate path, byte digest, and size;
  deletion revalidates the digest immediately before removal.
- Command presenters: map typed results to Rich or canonical JSON without changing
  domain decisions.

## Security Boundary

Assets are user images/PDFs and files reachable by the invoking account. CLI
arguments, discovered paths, file contents, and files changed between analysis and
apply are untrusted. Writes are limited to the explicit output root; deletes are
limited to revalidated byte-identical candidates. Resource exhaustion from very
large media remains a residual operational risk; callers processing untrusted
assets should additionally apply operating-system resource limits.

## Impact

- `core/files.py` becomes the sole output-path policy boundary.
- A shared metadata helper replaces hand-written orientation transforms.
- Batch commands validate the full task set before the first write.
- Similar-image groups remain advisory; only exact duplicates are deletable.
- Focused integration tests cover traversal, collisions, stale files, and JSON
  failure semantics.
