# ADR-0003: AI-native tool surface

## Status

Accepted

## Context

PixShift already exposes `--json` and optimize `plan` objects for automation, but
agents still reverse-engineer help text. Top AI-native tools expose a discoverable
catalog, constrained schemas, side-effect annotations, and a thin MCP adapter over
the same implementation as the CLI.

## Driving Factors

- CLI JSON remains the authoritative machine contract for scripts and shells.
- MCP must not become a second source of truth.
- Destructive and non-idempotent operations must be annotated for agent hosts.
- Media processing stays local; `openWorldHint` is false for core tools.
- Existing leaf commands stay specialized jobs (ADR-0002).

## Candidates

### Option A: CLI-only JSON improvements

- Pros: smallest change; no new runtime.
- Cons: agents without custom parsers still cannot discover tools or annotations.

### Option B: CLI JSON as authority + catalog/`apply` + optional MCP adapter

- Pros: one implementation path; shell agents and MCP hosts both work; annotations
  travel with the catalog.
- Cons: more surface area; schemas and catalog must stay in sync.

### Option C: MCP-first rewrite

- Pros: strongest native agent hosting.
- Cons: breaks shell/CI workflows; duplicates policy; too large for current phase.

## Decision

Chosen: **Option B**.

- Authoritative contract: UTF-8 JSON documents with `schema_version`, `command`, `ok`.
- `pixshift tools [--json]` publishes the stable catalog (name, description,
  when-to-use, input summary, annotations).
- `pixshift apply` executes machine plans produced by `optimize` (and later `prep`).
- Optional MCP server maps catalog entries to the same ops wrappers; it does not
  reimplement engines or safety policy.
- Annotations for every tool:
  - `readOnlyHint`
  - `destructiveHint`
  - `idempotentHint`
  - `openWorldHint` (always `false` for core local tools)

## Impact

- New modules: tool catalog, apply ops, schema fixtures, optional MCP entrypoint.
- Additive JSON fields only until a deliberate `schema_version` bump.
- Architecture docs and README restate AI-native positioning and non-goals.
