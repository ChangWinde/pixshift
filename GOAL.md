# PixShift Goal

## Destination

Agent (Cursor, Claude, scripts) and humans share one local-first media toolkit:
discover tools, plan transforms, apply them safely, and verify results with stable JSON.

PixShift is an **AI-native, agent-safe** image and PDF CLI: deterministic, auditable,
idempotent, and offline in the media hot path.

## Why Now

v1.1.0 already ships `--json`, safety ADRs, and optimize plans, but agents still lack
a discoverable catalog, schema-validated contracts, and a plan-to-apply loop.

## Current Focus

M0-M3 shipped in PR #11 (CI green on Python 3.10/3.12/3.13, frozen lockfile).
Trusted-publishing workflow is in place behind the `pypi` environment.

Next frontier, in order:

1. Merge PR #11.
2. One-time PyPI setup: trusted publisher (owner `ChangWinde`, repo `pixshift`,
   workflow `release.yml`, environment `pypi`) plus the GitHub `pypi`
   environment, then tag `v1.2.0` (see `docs/RELEASING.md`).
3. Coverage climb toward 80% (watch_engine and watermark_engine are the
   thinnest areas).
4. MkDocs documentation site.

## Milestones

| ID | Outcome | State |
|---|---|---|
| M0 | GOAL, ADR-0003, README AI-native positioning | COMPLETE |
| M1 | JSON Schema + CI; `tools`; `apply`; thin MCP | COMPLETE |
| M2 | pre-commit, stricter ruff, coverage 70%, uv CONTRIBUTING, shell completion | COMPLETE |
| M3 | `prep`, `manifest`, `hash`/`verify` for agent workflows | COMPLETE |

## In Scope

- Machine contracts (JSON Schema, tool catalog, MCP thin adapter)
- Engineering bar aligned with modern Python OSS
- Agent-frequent practical features that compose existing engines

## Out of Scope

- Generative / caption / LoRA models in the media hot path
- Matching ImageMagick feature breadth
- Breaking safety invariants for convenience
- A single opaque mega-run pipeline (see ADR-0002)

## Acceptance

- README and ADR state AI-native positioning and non-goals
- Schemas validate golden fixtures in CI
- Agents can discover tools via `pixshift tools --json` (and optional MCP)
- At least one plan to apply to verify path works end-to-end
- Phase-A quality gates from the AI-native roadmap are green

## Evidence

Commands, CI logs, schema fixtures, and CHANGELOG entries under each milestone.
