# PixShift Goal

## Destination

Agents (Cursor, Claude, scripts) and humans share one local-first media toolkit across
three pillars — images, PDFs, and video: discover tools, plan transforms, apply them
safely, and verify results with stable JSON.

PixShift is an **AI-native, agent-safe** media CLI: deterministic, auditable, idempotent,
and offline in the media hot path.

## Why Now

The image and PDF pillars ship `--json`, safety ADRs, optimize plans, a discoverable tool
catalog, schema-validated contracts, and a plan-to-apply loop. Everyday video work
(transcode, compress, trim, thumbnail, GIF) is the same kind of deterministic one-shot job
and the largest remaining gap for agent-driven media pipelines.

## Current Focus

Everything for `v1.2.0` is merged to a green `main`: the deep audit remediation, the
startup/dedup performance work, the ffmpeg-backed video pillar with its full
discover -> plan -> apply loop (probe-driven `optimize`, `apply` for `video.*`/`keep`,
opt-in `--hwaccel`), coverage 83% (gate 78), and a MkDocs site behind a Pages deploy
workflow.

The audit backlog is now empty: every P0-P3 finding from the 32-agent deep
audit is either fixed or explicitly retired.

Next frontier, in order:

1. Release `v1.3.0` (the first PyPI release of the modern toolkit; `v1.2.0`
   was never tagged and its content ships within 1.3.0) — maintainer web
   steps: PyPI trusted publisher + `pypi` environment, enable Pages (Source:
   GitHub Actions), then tag and push `v1.3.0` (see `docs/RELEASING.md`).
2. Post-release: gather real-world agent feedback before opening new scope;
   candidate directions live in ADR-0004/0005 non-goals reviews.

## Milestones

| ID | Outcome | State |
|---|---|---|
| M0 | GOAL, ADR-0003, README AI-native positioning | COMPLETE |
| M1 | JSON Schema + CI; `tools`; `apply`; thin MCP | COMPLETE |
| M2 | pre-commit, stricter ruff, coverage 70%, uv CONTRIBUTING, shell completion | COMPLETE |
| M3 | `prep`, `manifest`, `hash` for agent workflows | COMPLETE |
| M4 | Deep-audit remediation: metadata/privacy, compress/PDF correctness, apply/MCP hardening | COMPLETE |
| M5 | Performance: lazy startup (RSS 132MB to 41MB), parallel + draft dedup | COMPLETE |
| M6 | Video pillar MVP: `video info/convert/compress/trim/thumbnail/extract-audio/gif`; ffmpeg in `doctor`; catalog + tests (ADR-0005) | COMPLETE |
| M7 | Video plan loop: probe-driven `optimize`, `apply` for `video.*`/`keep`; coverage 82% (gate 78) | COMPLETE |
| M8 | Release readiness: `--hwaccel` opt-in, video command docs, MkDocs site + Pages workflow, v1.2.0 release commit | COMPLETE |
| M9 | Animated-image transforms (frames preserved through convert/resize/optimize) + pdf merge JPEG byte-splice (4.3x, metadata-clean) | COMPLETE |
| M10 | Audit backlog cleared: exit-code contract + failure objects (schema 1.1), JSON polish, pdf compress rect index (2.7x), batch UI consistency | COMPLETE |

## In Scope

- Machine contracts (JSON Schema, tool catalog, MCP thin adapter)
- Engineering bar aligned with modern Python OSS
- Agent-frequent practical features that compose existing engines

## Out of Scope

- Generative / caption / LoRA models in the media hot path (all three pillars)
- Matching ImageMagick or the full ffmpeg flag surface
- Video timeline/NLE editing, filter/effect chains, subtitle burn-in
- Cloud transcoding, render farms, live-streaming protocols (RTMP/HLS)
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
