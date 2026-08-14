# ADR-0006: Extreme-quality verification and shared policy boundaries

## Status

Accepted

## Context

The pre-2.0 audit found that green unit tests did not prove several user-visible
properties: colour-managed conversion, preservation of document and stream
semantics, highest-quality size-budget selection, and no-clobber publication
under concurrency. It also found policy drift between direct CLI commands,
`apply`, `prep`, and MCP.

“Extreme quality” therefore means a result is both faithful and provable:

- pixels, colour, frames, pages, streams, and metadata follow an explicit policy;
- requested byte budgets select the highest feasible quality without hidden resizing;
- invalid work is rejected before media files are written;
- publication remains atomic, no-clobber, and permission-preserving at commit time;
- agents can enforce postconditions through stable JSON rather than prose.

Generative processing, a full editor/NLE, cloud rendering, and an
ImageMagick-complete surface remain out of scope.

## Candidates

### Option A: Replace every operation with one typed registry now

Define a universal request/result algebra and migrate every CLI command, engine,
`apply`, and MCP call in one release.

- Pros: strongest compile-time uniformity and one dispatch mechanism.
- Cons: a high-risk rewrite across three mature media pillars; large compatibility
  and review surface unrelated to the proven failures.

### Option B: Strengthen shared boundaries and add a narrow verifier

Keep engines and result dataclasses, but make shared policy authoritative:

- core owns file identity, output publication, pixel budgets, colour conversion,
  and stable error categories;
- ops owns semantic parameter validation and complete batch planning;
- CLI and MCP remain adapters;
- a new `verify` operation dispatches to media-specific validators behind one
  result contract.

- Pros: fixes the demonstrated failure classes at their common boundary, preserves
  compatible APIs, and can be regression-tested incrementally.
- Cons: existing media-specific result dataclasses remain; migration discipline is
  still required when adding commands.

### Option C: Patch each failing command locally

- Pros: smallest individual diffs.
- Cons: repeats the architecture drift that caused the failures and cannot make
  no-clobber, metadata, plan, or error guarantees consistent.

## Decision

Choose **Option B**.

The service interfaces are:

```text
plan(request) -> validated tasks | stable usage error
publish(candidate, destination, overwrite) -> committed | output_exists
convert_colour(image, target, preserve_profile) -> pixels + output profile + warnings
verify(source, candidate, thresholds) -> typed checks + pass/fail + stable error
```

`verify SOURCE CANDIDATE` supports images, PDFs, and videos. It checks structural
invariants for every pillar and deterministic perceptual similarity where a local
backend exists. A requested unavailable metric fails explicitly; it never silently
downgrades to a weaker check. Threshold failure is an attempted verification failure
(exit 1), while invalid thresholds or unsupported input pairs are rejected before
work (exit 2).

Image conversion gains an explicit `preserve|srgb` colour policy. `srgb` uses the
embedded profile through LittleCMS and embeds the resulting sRGB profile; an invalid
source profile is reported instead of being relabelled. Video gains an explicit
`preserve|compatible|compact` audio policy. Loss or fallback is disclosed in JSON.

## Consequences

- Existing direct commands, plans, and MCP calls must share validators; dry-run uses
  the same validation and planning path as execution.
- No-overwrite is enforced at publication, not only by an earlier existence check.
- Format-specific semantic loss is preserved, rejected, or disclosed; silent loss is
  not a successful outcome.
- `tools --json`, schemas, docs, and regression tests form one enumerated contract.
- The full registry rewrite remains a future option only if incremental boundaries
  prove insufficient; it is not required to close this audit.
