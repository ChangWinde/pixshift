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

M0-M3 shipped; the deep audit remediation (privacy/metadata, compress/PDF correctness,
apply/MCP hardening) and the startup/dedup performance work are landed with tests, and the
optional ffmpeg-backed video pillar (ADR-0005) is in.

Next frontier, in order:

1. Merge PR #18 (surface audit) and the audit-remediation branch; then one-time PyPI
   trusted-publisher setup and tag `v1.2.0` (see `docs/RELEASING.md`).
2. Coverage climb toward 80% including the new video argv builders.
3. Video pillar depth: probe-driven `optimize` for video, plan/apply support for
   `video.*`, hardware-accel opt-in.
4. Animated-image transforms (GIF/APNG to animated WebP) — the image-to-video
   bridge (ADR-0004 gap, ADR-0005 scope).
5. MkDocs documentation site organised by the three pillars.

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
