# First Public Release PR

Use this file as the source for the first formal release pull request.

## Suggested PR Title

`release: first public launch - unified CLI architecture, JSON automation, and advanced workflows`

## Suggested Labels

- `release`
- `breaking-risk:low`
- `type:feature`
- `area:cli`
- `area:docs`
- `area:ci`
- `area:tests`

## PR Description (Copy/Paste)

### Why

This PR prepares PixShift for its first formal public release with a stable,
automation-friendly CLI, improved architecture layering, stronger open-source
governance, and validated quality gates.

### Change Groups

#### 1) Product Surface

- Promoted high-frequency workflows to top-level commands:
  - `convert`, `compress`, `strip`, `dedup`
- Added advanced workflows:
  - `compare`, `crop`, `watermark`, `montage`, `optimize`, `watch`
- Completed PDF command set:
  - `pdf merge`, `pdf extract`, `pdf compress`, `pdf concat`, `pdf info`
- Added safer destructive flow support:
  - `dedup --delete --dry-run`

#### 2) Automation & Output Contract

- Added and standardized `--json` output for:
  - core workflow commands
  - advanced commands
  - system commands (`info`, `formats`, `doctor`)
  - PDF commands
- Unified JSON exit-code semantics:
  - success: `0`
  - command failure / validation failure: `1`

#### 3) Architecture & Internal Design

- Refactored monolithic CLI into modular command registration:
  - `commands/convert_command.py`
  - `commands/workflow_commands.py`
  - `commands/pdf_commands.py`
  - `commands/system_commands.py`
  - `commands/advanced_commands.py`
- Added shared `core` layer:
  - `core/files.py`
  - `core/models.py`
- Introduced `ops` wrappers to separate command orchestration from engine calls.

#### 4) Correctness, UX, and Safety

- Tightened format support claims to runtime capability detection.
- Unified output planning and path behavior.
- Enforced confirmations for destructive flows.
- Normalized key command flags (`-o`, `-r`, `--overwrite`, `--dry-run`) across major workflows.

#### 5) Testing, CI, and Release Engineering

- Bootstrapped regression suite with command, JSON, and fixture tests.
- Added advanced command JSON tests and command smoke coverage.
- Raised enforced coverage gate to `50%` in CI/release workflows.
- Added release build validation (`build` + `twine check`).

#### 6) Open-Source Readiness

- Added issue templates, PR template, contributing and policy docs.
- Added security and support documentation.
- Added Dependabot and CI workflows.
- Added command reference and runnable automation/advanced examples.

### Validation

- `python -m pytest -q`
- `python -m pytest -q --cov=pixshift --cov-report=term-missing --cov-fail-under=50`
- Core CLI help and advanced command help checks

### Risk

Low to medium. Main risk comes from broad command-surface expansion; mitigated by
test coverage, JSON contract docs, and smoke checks.

### Follow-ups (Post-release)

- Expand engine-level tests for `watermark`, `watch`, and `crop`.
- Add benchmark baselines for common workflows.
- Consider trusted publishing automation for PyPI.

## Maintainer Checklist

- [ ] Changelog reviewed and finalized
- [ ] Release notes reviewed
- [ ] CI green on PR
- [ ] Tag plan confirmed (`v1.0.0` or chosen release tag)
- [ ] Post-merge release runbook followed (`docs/RELEASING.md`)

