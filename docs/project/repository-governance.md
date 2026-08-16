# Repository Governance

This page is the mutable source of truth for GitHub-hosted controls that cannot be proven
from a checkout alone. ADR-0009 records why these controls exist; this page records the
current expected state and how maintainers verify it.

## Required State

| Surface | Required policy |
| --- | --- |
| Default branch | `main`; pull request required; required CI and CodeQL checks; resolved conversations; no deletion or force push |
| Release tags | `v*`; deletion and updates rejected; release workflow accepts annotated tags only |
| Pages | GitHub Actions build type; read-only build job; `github-pages` deployment environment; no generated `gh-pages` branch |
| PyPI | `pypi` environment with an explicit reviewer; OIDC trusted publisher; tag-only release workflow |
| Dependency security | Dependabot alerts and automated security updates enabled; weekly uv and Actions update configuration tracked |
| Code and secret scanning | CodeQL workflow active; secret scanning and push protection enabled; no unresolved alerts |
| Repository metadata | Documentation homepage set; description covers image, PDF, and video; merged branches deleted automatically; Wiki disabled to avoid a second documentation authority |

The required checks use their exact GitHub check-run names. When the CI matrix changes,
update the active `main` ruleset in the same governance change; a stale required check can
either weaken protection or make the branch impossible to merge.

## Read-only Audit

Run the following with an authenticated GitHub CLI before a release or after a settings
change:

```bash
gh repo view ChangWinde/pixshift --json defaultBranchRef,description,homepageUrl,deleteBranchOnMerge
gh api repos/ChangWinde/pixshift/rulesets
gh api repos/ChangWinde/pixshift/environments
gh api repos/ChangWinde/pixshift/pages
gh api repos/ChangWinde/pixshift/vulnerability-alerts
gh api repos/ChangWinde/pixshift/automated-security-fixes
gh api repos/ChangWinde/pixshift/code-scanning/alerts
gh api repos/ChangWinde/pixshift/secret-scanning/alerts
git ls-remote --heads --tags origin
```

An empty alert list is evidence only when the corresponding feature is enabled and its
latest workflow completed successfully. A `404` or `403` from a security endpoint must not
be interpreted as “no findings.” PyPI's trusted-publisher association is verified in the
PyPI project settings because GitHub cannot introspect it.

## Change Procedure

1. Record a structural policy change in a superseding ADR before applying it.
2. Update workflows, documentation, and repository-governance tests in one pull request.
3. Apply external settings through the GitHub API with the smallest required permissions.
4. Read the settings back, exercise the affected workflow, and retain the run or deployment
   URL as evidence.
5. Remove superseded generated branches or environments only after the replacement is live.

Repository settings are production state. Never disable a rule merely to merge a failing
change; fix the change or deliberately supersede the policy with reviewed evidence.
