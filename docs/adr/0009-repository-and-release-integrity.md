# ADR-0009: Repository and release integrity

## Status

Accepted

## Context

ADR-0007 made the tracked repository understandable, but two platform-level gaps remained.
The published manual was deployed by pushing generated files to `gh-pages`, which required
checkout credentials with repository write access. Branch, tag, release, and dependency
security policies also existed mainly as maintainer instructions instead of enforced GitHub
configuration. Those controls are part of the delivery boundary: a clean worktree cannot
prove that `main`, a version tag, or a PyPI deployment is protected.

ADR-0007's root inventory also omitted `MANIFEST.in` after native runtime packaging was
introduced. Removing that conventional setuptools manifest would make source-distribution
contents less discoverable and would replace an ecosystem entry point with custom build
logic.

## Candidates

| Option | Pages credential exposure | Policy enforcement | Release evidence | Compatibility |
| --- | --- | --- | --- | --- |
| A. Keep branch-based Pages and written checklists | Write token in the build job | Manual | Package hashes only | High |
| B. Keep `gh-pages`, but inject a narrowly scoped deploy token | Narrower, but still present during build | Mixed | Package hashes and optional signatures | High |
| C. Deploy a Pages artifact and enforce repository/release policy in GitHub | Build is read-only; deploy uses short-lived OIDC | Platform-enforced | SBOM, checksums, and signed attestations | High |

Option A is simple but lets configuration drift silently. Option B reduces token scope but
still couples documentation generation to Git publication and retains a generated branch.
Option C separates build from deployment, removes the generated branch, and makes the same
policy visible to maintainers, automation, and GitHub.

## Decision

Choose **Option C**.

- Documentation builds with read-only repository access, uploads a Pages artifact, and is
  deployed by GitHub's Pages action with `pages: write` and OIDC only in the deploy job.
- `main` is governed by an active ruleset: changes arrive through pull requests, required
  CI checks pass, conversations are resolved, and deletion or non-fast-forward updates are
  rejected.
- `v*` tags are immutable after creation. Release automation requires an annotated tag
  whose version matches `pyproject.toml`.
- The PyPI job uses a protected `pypi` environment and trusted-publisher OIDC. It emits
  SHA-256 checksums, an SPDX SBOM, build-provenance and SBOM attestations before publishing,
  then creates the corresponding GitHub Release.
- CodeQL, Dependabot alerts, automated security updates, secret scanning, and push
  protection are repository security controls, not optional local tooling.
- Third-party actions are pinned to immutable commit SHAs; checkout credentials are disabled
  unless a job has a reviewed need to push.

`MANIFEST.in` is added to the curated root contract. It is a conventional packaging
entry point required to make authenticated native-runtime inputs and release verification
scripts part of the source distribution. This supersedes only ADR-0007's enumerated root
file list; its audience, placement, and source-of-truth rules remain in force.

## Enforcement

- `tests/repository/test_docs_governance.py` verifies the workflow and root-layout contracts.
- [Repository governance](../project/repository-governance.md) records the expected external
  GitHub state and read-only audit commands.
- The release workflow rejects lightweight or version-mismatched tags before building.
- GitHub rulesets, environments, code scanning, dependency alerts, and Pages settings are
  verified after every governance change and before a release.

## Consequences

- Documentation publication no longer needs a generated Git branch or a write credential in
  the build job.
- A release carries machine-verifiable integrity and dependency evidence in addition to the
  package files.
- Some controls live outside Git, so the repository-governance audit is a required part of
  release readiness and cannot be inferred from CI YAML alone.
- Historical lightweight tags remain historical evidence and are not rewritten; all future
  releases follow the annotated, immutable tag policy.
