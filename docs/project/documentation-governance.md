# Documentation Governance

PixShift documentation is part of the product contract. This policy assigns every
document an audience, a source-of-truth role, and a verification path so that code,
automation clients, release metadata, and the published manual do not drift apart.

## Information Architecture

| Location | Audience | Authority | Language | Published on the manual site |
| --- | --- | --- | --- | --- |
| `README.md` | Evaluators and new contributors | Product promise, fast orientation, repository map | English | No |
| `docs/*.md` | CLI users and automation authors | Current supported workflows and public behavior | Chinese | Yes |
| `docs/schemas/v1/` | Programs and agents | JSON payload structure for schema 1.1 | JSON/English | Served as static contracts |
| `docs/project/` | Maintainers and contributors | Current architecture, process, goals, and evidence | English | No |
| `docs/adr/` | Maintainers and reviewers | Immutable architectural decisions and tradeoffs | English | No |
| `.github/` | Contributors and repository hosts | Contribution, support, security, review, and CI policy | English | No |
| `AGENTS.md` | Coding agents | Safe invocation and repository-local operating rules | English | No |
| `CHANGELOG.md` | Users and release tooling | Versioned release history and migrations | English | No |

The placement rationale and root-file budget are recorded in
[ADR-0007](../adr/0007-repository-documentation-governance.md).

## Source-of-truth Rules

One claim must have one primary authority:

- CLI option names, defaults, and accepted values originate in code and must be mirrored
  in the relevant manual page from real `--help` output.
- JSON field types and required keys originate in [`docs/schemas/v1/`](../schemas/v1/).
- Shared safety and architecture decisions originate in ADRs; the
  [architecture overview](architecture.md) describes the current result.
- Version numbers originate in `pyproject.toml`; published changes and migrations belong
  in `CHANGELOG.md`.
- Quality commands and their exact thresholds originate in CI. Contributor and release
  instructions may repeat them only when governance tests compare those copies.
- Measured performance claims require a reproducible command, data-generation method,
  environment note, and correctness oracle in [performance.md](performance.md).

The README summarizes these authorities; it must link to detail instead of becoming a
second exhaustive command manual.

## Review Ownership

[`CODEOWNERS`](../../.github/CODEOWNERS) assigns the current repository and its
documentation surfaces to `@ChangWinde`. The explicit documentation entries make the
review boundary visible and allow ownership to be split later without redesigning this
policy. A requested owner review is routing, not proof of correctness; the change still
needs the semantic and mechanical checks below.

## Change-impact Matrix

| Change | Documentation that must be reviewed in the same pull request |
| --- | --- |
| Command, flag, default, or error behavior | Relevant user-manual chapter, `README.md` quick examples if affected, tool catalog, examples |
| JSON field or exit semantics | Schema files, `docs/JSON_OUTPUT.md`, `docs/automation.md`, `AGENTS.md`, compatibility notes |
| Safety or quality invariant | Relevant manual warning, architecture overview, a new or superseding ADR, regression tests |
| Dependency or platform support | `docs/install.md`, `pixshift doctor`, package metadata, CI matrix |
| Release/version change | `pyproject.toml`, `uv.lock`, `CHANGELOG.md`, [releasing.md](releasing.md) |
| Performance claim | Benchmark harness and [performance.md](performance.md); never README-only numbers |
| Documentation structure | `mkdocs.yml`, link checks, this governance page, redirects if a public URL moves |

“No documentation impact” is a reviewable conclusion, not a default checkbox.

## Authoring Lifecycle

1. **Classify the audience.** Put user instructions, machine contracts, maintainer
   process, decisions, and community policy in their assigned homes.
2. **Update with the implementation.** Behavior and its documentation ship in the same
   change set; do not create a follow-up documentation debt item for a public contract.
3. **Verify mechanically.** Run the focused governance tests and a strict site build.
4. **Review semantically.** Confirm examples work, warnings describe failure behavior,
   links lead to the authoritative page, and claims do not exceed what tests prove.
5. **Publish from `main`.** The Pages workflow deploys the manual only after a successful
   strict build. A green local build does not mean the public site has deployed.
6. **Retire deliberately.** Preserve release history. Supersede ADRs instead of rewriting
   accepted decisions; when a public page moves, provide a redirect before removing its URL.

## Writing Standards

- Start each page with one level-one heading and a one-paragraph statement of purpose.
- Prefer runnable commands and exact failure semantics over promotional adjectives.
- Use repository-relative Markdown links for checked-in engineering material. The README
  uses canonical HTTPS GitHub links because the same long description renders on PyPI;
  the public manual and external authorities also use HTTPS.
- Keep user-facing prose in Chinese, matching the CLI; keep contributor and engineering
  material in English unless a localized section has a named owner.
- Treat numbers, platform claims, supported formats, and current versions as volatile.
  Tie them to code/CI where possible and remove unsupported snapshots.
- Comments explain a decision or constraint. File names and headings should already
  explain structure.
- Avoid orphan pages. Every Markdown file below `docs/` must be in the MkDocs navigation
  or covered by an explicit excluded directory.

## Required Checks

Run the focused documentation gate while authoring:

```bash
uv run pytest -q tests/repository/test_docs_governance.py
uv run mkdocs build --strict
```

Before merge, run the repository gate documented in
[the contributor guide](../../.github/CONTRIBUTING.md). The governance test proves
machine-checkable relationships: it does not prove clarity, translation quality,
accessibility, or that an example communicates the intended workflow. Those remain human
review responsibilities.

## Publication and Incident Handling

The [Docs workflow](../../.github/workflows/docs.yml) deploys changes to
<https://changwinde.github.io/pixshift/> when `docs/**`, `mkdocs.yml`, or the workflow
itself changes on `main`. If the site is stale:

1. compare the deployed page with the corresponding source file;
2. inspect the latest Docs workflow run, not only the general CI workflow;
3. reproduce with `uv run mkdocs build --strict`;
4. fix the source or deployment configuration without editing the generated `site/` tree;
5. verify the deployed URL after the next successful publish.

Generated `site/`, `dist/`, coverage files, caches, virtual environments, and egg-info are
local build state. They are ignored and must never be treated as documentation sources.
