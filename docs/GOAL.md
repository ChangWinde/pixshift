# PixShift Goal

## Destination

Agents (Cursor, Claude, scripts) and humans share one local-first media toolkit across
three pillars — images, PDFs, and video: discover tools, plan transforms, apply them
safely, and verify results with stable JSON.

PixShift is an **AI-native, agent-safe** media CLI: deterministic, auditable, idempotent,
and offline in the media hot path.

## Why This Shape

Media work is a long tail of one-shot jobs: convert this, shrink that under a
size cap, strip the GPS, join these clips. Tools that serve it well are boring
and predictable, not clever. Every design decision follows from that: one verb
per command instead of a pipeline DSL, deterministic plans instead of hidden
heuristics, stable JSON so an agent needs no screen scraping, and safety
invariants (atomic writes, idempotent reruns, opt-in destruction) that hold
identically for a human at a prompt and for an unattended script.

## Current Focus

All three pillars are complete and verified on a green `main`: images, PDF, and
the ffmpeg-backed video pillar, each with the full discover -> plan -> apply
loop and the shared `--target-size` idiom. Coverage is about 85% (gate 78),
CI runs on Linux, macOS, and Windows, the video runtime is exercised against a
real ffmpeg, and the user manual is live at
<https://changwinde.github.io/pixshift/>.

The audit backlog is empty: every P0-P3 finding from the 32-agent deep audit is
either fixed or explicitly retired.

Next frontier, in order:

1. Release `v1.3.0` (the first PyPI release of the modern toolkit; `v1.2.0`
   was never tagged and its content ships within 1.3.0) — maintainer steps:
   PyPI trusted publisher + `pypi` environment, then tag and push `v1.3.0`
   (see `docs/RELEASING.md`).
2. Post-release: gather real-world agent feedback before opening new scope;
   candidate directions live in the ADR-0004/0005 non-goals reviews.

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
| M11 | Size budgets on every pillar + `video concat`; batch surfaces parallelised (4-4.5x) | COMPLETE |
| M12 | Verification depth: real-ffmpeg runtime tests, property fuzzing, e2e sweep harness, CI on Linux/macOS/Windows | COMPLETE |
| M13 | Chinese user manual published; documentation governance enforced in CI | COMPLETE |

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

- README and ADRs state the AI-native positioning and the non-goals
- JSON Schemas validate live command output in CI
- Agents can discover tools via `pixshift tools --json` (and the optional MCP adapter)
- The plan -> apply -> verify path works end to end for images, PDF, and video
- Quality gates are green on Linux, macOS, and Windows: lint, format, types,
  the full test suite with its coverage floor, and a strict documentation build

## Evidence

Commands, CI logs, schema fixtures, and CHANGELOG entries under each milestone.
