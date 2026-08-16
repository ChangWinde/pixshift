# ADR-0007: Contract-aware repository and documentation layout

## Status

Superseded in part by [ADR-0009](0009-repository-and-release-integrity.md)

## Context

PixShift had ten tracked files and seven tracked directories at the repository root.
The file count was modest, but three different concerns were mixed together:

- ecosystem entry points that tools discover only by convention;
- GitHub community policy and repository branding;
- user documentation, engineering references, and historical records in one flat
  `docs/` directory.

The visible checkout also accumulates ignored build products and tool caches. Those
artifacts are local workspace state, not repository structure, and should not drive a
tracked-file migration.

Any reorganisation must preserve zero-configuration commands (`uv sync`, `pip install .`,
`pre-commit install`, `mkdocs build`), GitHub community-file discovery, published manual
URLs, package metadata, and agent discovery through the root `AGENTS.md`.

## Candidates

| Option | Root clarity | Tool compatibility | Documentation clarity | Migration risk |
| --- | --- | --- | --- | --- |
| A. Keep the existing flat layout | Low | High | Low | Low |
| B. Move almost every root file under `config/` or `docs/` | High | Low; common tools need explicit flags or wrappers | Medium | High |
| C. Keep conventional entry points; group repository-owned material by audience | High | High | High | Low |

### Option A: Preserve the layout

This avoids churn, but it leaves contributor policy and brand assets at the same level as
build metadata. Engineering references continue to compete with the published manual in
`docs/`, and no rule prevents future drift.

### Option B: Create a nearly empty root

Configuration, lock, license, agent, and project files could all move below dedicated
directories. The result looks compact, but Python packaging, uv, pre-commit, MkDocs,
GitHub, and coding agents rely on conventional default locations. Wrapper commands and
extra CI flags would replace familiar ecosystem behavior with PixShift-specific ceremony.

### Option C: Use contract-aware placement

Keep files at the root only when discoverability, packaging, licensing, release history,
or zero-configuration tooling benefits from the conventional location. Move GitHub-owned
policy and presentation into `.github/`; group maintainer references in `docs/project/`;
keep the small public manual at `docs/` root so existing URLs remain stable.

## Decision

Choose **Option C**.

The repository root is a curated compatibility surface, not a generic storage location.
Its tracked files are limited to:

- `.gitignore` and `.pre-commit-config.yaml`;
- `pyproject.toml`, `uv.lock`, and `mkdocs.yml`;
- `README.md`, `LICENSE`, `CHANGELOG.md`, and `AGENTS.md`.

GitHub community documents, templates, workflows, and brand assets live in `.github/`.
The published Chinese manual stays at the `docs/` root to preserve its established page
URLs. Versioned schemas stay under `docs/schemas/`, accepted decisions under `docs/adr/`,
and mutable maintainer references under `docs/project/`. Tests are grouped below
`tests/` by their owning product or policy boundary; production modules keep their
existing import paths because those paths have compatibility cost.

Documentation has one named source of truth per claim. User behavior belongs in the
relevant manual chapter, machine payload shape in JSON Schema, architecture rationale in
ADRs, current component structure in the architecture overview, release history in the
changelog, and operational process in the project governance references. A behavior
change updates every affected authority in the same pull request.

## Enforcement

- `tests/repository/test_docs_governance.py` checks placement, navigation, links,
  command coverage,
  metadata URLs, version claims, and cross-file policy values.
- `mkdocs build --strict` rejects an invalid site before deployment.
- The pull request template asks authors to classify documentation impact and name the
  source-of-truth pages they changed.
- The Pages workflow publishes only after a strict build from `main`.

## Consequences

- The root remains familiar to Python, GitHub, documentation, and agent tooling while
  containing one fewer tracked file and one fewer tracked directory.
- Engineering references have a clear home and can grow without flattening `docs/`.
- Public manual URLs do not change as a side effect of repository housekeeping.
- Moving a conventional root file now requires a superseding ADR with evidence that the
  relevant ecosystem supports the new location without wrapper-only workflows.
- Ignored caches and build outputs may still exist in a developer checkout; they are
  disposable local state and remain excluded through `.gitignore`.
