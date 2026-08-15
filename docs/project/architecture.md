# PixShift Architecture

PixShift is a local-first CLI. Click commands translate user intent, operation
wrappers provide a narrow service boundary, engines perform the image, PDF, and
video work, and shared core modules enforce invariants that must not vary by
command.

## Runtime Layers

```text
CLI commands
  ├─ validate options and build complete task plans (usage errors exit 2)
  ├─ Rich presenter (human output, shared batch progress)
  └─ JSON presenter (schema_version 1.1)
          │
          ▼
ops wrappers
          │
          ▼
image / PDF / video engines
  (PyMuPDF is a required, lazily imported package; ffmpeg is an optional system
   dependency reported by doctor; video argv builders are pure functions)
          │
          ▼
core policy
  ├─ files.py        collection, root containment, collision checks, atomic writes
  ├─ defaults.py     canonical human and automation defaults
  ├─ metadata.py     frame, transparency, orientation, and EXIF policy
  ├─ errors.py       stable policy error codes
  ├─ parallel.py     bounded, order-preserving batch execution
  ├─ tool_catalog.py the agent-facing catalog with side-effect annotations
  └─ models.py       shared batch summaries
```

Commands remain adapters: they may select options and presentation, but must not
reimplement path, deletion, or metadata safety decisions.

## Product Surface

The primary workflows are `convert`, `compress`, `strip`, and `dedup`. Focused
utilities (`compare`, `crop`, `resize`, `rotate`, `watermark`, `montage`,
`optimize`, `verify`, the `pdf` group, and the ffmpeg-backed `video` group) stay
independent so users do not need to configure a large pipeline for a single
operation. Agent workflow commands (`tools`, `apply`, `prep`, `manifest`,
`hash`) close the discover → plan → apply → verify loop. Root help
intentionally stays compact; detailed options live under each command.

## Safety Invariants

- A full batch is planned and checked for destination collisions before writing.
- Directory-discovered generated artifacts are excluded at the shared planning boundary;
  explicit inputs remain authoritative.
- Existing outputs are successful derivative-batch skips unless overwrite is
  explicit; aggregate outputs that alias any input are rejected.
- A generated path stays below the explicitly selected output root.
- Encoders write inside a private temporary directory. POSIX publication then
  copies into a no-follow, dirfd-bound staging file and commits relative to that
  descriptor. Windows holds a no-delete-share handle for every verified parent
  and the staging directory, rejecting reparse points. Concurrent symlink or
  junction swaps therefore cannot redirect publication on either platform.
- Pixel-changing operations normalize EXIF Orientation exactly once and remove the
  consumed tag.
- Animation is preserved or refused, never silently flattened: `convert` and
  `resize` carry frames/timing/loop through to animation-capable targets,
  pixel-compositing operations reject multi-frame input before output
  mutation, and opaque encoders use one canonical transparency policy.
- Similar-image groups are advisory. Automatic deletion is limited to byte-identical
  files whose size and SHA-256 digest are revalidated immediately before removal.
- An impossible target-size request fails without leaving a misleading output.
- JSON documents with `ok: false` terminate with a non-zero exit code:
  `1` after attempted work fails, `2` when the invocation is rejected before
  any output is written.

The accepted designs and alternatives are recorded in
[ADR-0001](../adr/0001-safe-operation-boundaries.md) and
[ADR-0002](../adr/0002-opinionated-defaults-and-ai-plans.md). The extreme-quality
policy and media verification boundary are recorded in
[ADR-0006](../adr/0006-extreme-quality-boundaries.md).

## Repository Information Architecture

Repository placement follows
[ADR-0007](../adr/0007-repository-documentation-governance.md):

```text
repository root        conventional discovery, packaging, license, and release entry points
.github/               contributor policy, review templates, workflows, and brand assets
docs/                  published manual and versioned JSON schemas
docs/project/          mutable maintainer references and operational evidence
docs/adr/              immutable accepted decisions
examples/              runnable user and automation journeys
scripts/               repository verification and benchmark harnesses
tests/                 suites grouped by product and policy ownership boundary
```

The root is a compatibility surface rather than a storage bucket. Public manual pages
remain directly below `docs/` so established URLs stay stable; engineering material is
grouped by audience and excluded from the site. The ownership, update matrix, retirement
policy, and validation gates live in
[documentation-governance.md](documentation-governance.md).

## Automation and AI Clients

AI and scripts use the same deterministic CLI contract as humans. Every JSON
document contains `schema_version`, `command`, and `ok`; paths and numeric sizes
are explicit, Click parsing failures use the same JSON channel, and dry-run modes
expose complete previews. No model call sits in the media-processing hot path, so
local performance and reproducibility do not depend on network availability.
`optimize` returns a structured command plan and explicitly marks sampled estimates,
so agents can act without parsing localized prose or treating estimates as exact facts.

The contract layer (ADR-0003) makes this surface discoverable and verifiable:

- `core/tool_catalog.py` publishes the stable catalog with MCP-aligned
  side-effect annotations; `pixshift tools --json` exposes it to shell agents.
- `pixshift apply` executes plans emitted by `optimize` (and future planners)
  through the same ops wrappers as interactive commands.
- `docs/schemas/v1/` holds the shared envelope and dedicated schemas for the
  automation/verification payloads; CI validates live outputs against them,
  and breaking changes require a `schema_version` bump.
- `pixshift.mcp` is a thin stdio JSON-RPC adapter that maps catalog entries to
  CLI invocations; it never reimplements engines or safety policy.

## Performance Model

- Single-file conversion stays in-process to avoid process startup overhead.
- Batch conversion uses at most eight workers and further reduces concurrency
  against an estimated decode-memory budget; callers can request a lower limit
  with `--jobs`.
- Image comparison deterministically samples very large inputs and discloses the
  sample scale instead of retaining multiple full-resolution working copies.
- Perceptual duplicate search uses multi-index hashing plus union-find instead of
  comparing every pair. Threshold zero uses direct hash grouping.
- Exact-file SHA-256 is computed only for equal-size candidates.
- Target-size compression encodes in memory and atomically writes the exact tested
  payload, avoiding a second unverified encode.
- Format analysis bounds large images to a 1600 px sample before trial encodes;
  video and animation analysis is probe-driven and never encodes at plan time.
- `pdf merge` splices eligible single-scan JPEG bytes (metadata-stripped and
  verified through the exact EOI) instead of re-encoding; `pdf compress`
  resolves image placement rects once per page.
- Startup defers PyMuPDF and encoder probing so non-PDF commands stay light.

## Quality Gates

CI runs Ruff lint/format checks, mypy, the full pytest suite (including
property-based contract tests), and a 78% coverage floor; the tag-driven
release workflow adds package build/metadata validation, and the docs workflow
builds the MkDocs site strictly. Dependencies are resolved from `uv.lock`, and
third-party GitHub Actions are pinned to immutable commit SHAs.
