# Label Strategy

This document defines the recommended label taxonomy for PixShift.

## Type Labels

- `type:feature`
- `type:bug`
- `type:refactor`
- `type:docs`
- `type:test`
- `type:ci`
- `type:release`

## Area Labels

- `area:cli`
- `area:core`
- `area:ops`
- `area:pdf`
- `area:docs`
- `area:examples`
- `area:ci`
- `area:governance`

## Priority Labels

- `priority:p0`
- `priority:p1`
- `priority:p2`
- `priority:p3`

## Risk Labels

- `breaking-risk:low`
- `breaking-risk:medium`
- `breaking-risk:high`

## Lifecycle Labels

- `status:needs-triage`
- `status:in-progress`
- `status:blocked`
- `status:ready-for-review`
- `status:ready-to-merge`

## Suggested Defaults

- New issue: `status:needs-triage`
- Bug issue: `type:bug` + area label + priority label
- Feature issue: `type:feature` + area label + priority label
- Release PR: `type:release` + `area:ci` + `area:docs` + risk label

