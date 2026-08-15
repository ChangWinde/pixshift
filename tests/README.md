# Test Suite Layout

Tests are grouped by the behavior or boundary that owns the assertion. Pytest still
discovers every module recursively with `uv run pytest`; the directories are navigation,
not separate execution tiers.

| Directory | Scope |
| --- | --- |
| `automation/` | Tool catalog, plans, ops wrappers, schemas, MCP, and machine contracts |
| `cli/` | Command registration, presenters, human output, JSON envelopes, and exit behavior |
| `core/` | Shared file policy, atomic publication, and bounded parallel execution |
| `image/` | Image conversion, metadata, animation, format, and lifecycle behavior |
| `integration/` | Cross-pillar defaults, safety, target-size, transform, and verification journeys |
| `pdf/` | PDF engine semantics, workflows, and JPEG splice behavior |
| `repository/` | Documentation, textual policy, and commit-message governance |
| `video/` | Video argv, ops, optimization, runtime, hardware, and real-ffmpeg journeys |

Choose the narrowest directory that owns the behavior. A test that deliberately crosses
two or more media pillars belongs in `integration/`; a CLI test does not move to `cli/`
when a single domain still owns its behavior. Shared fixtures should be introduced only
when repeated setup has identical semantics across those owners.

Run a focused suite during development, then the whole repository gate:

```bash
uv run pytest -q tests/pdf
uv run pytest -q
```
