# Security Policy

## Supported Versions

Security fixes are provided for the latest published release line.

Supported platform wheels include a pinned FFmpeg runtime. A vulnerability in that
runtime or its static codec libraries is in scope for this policy. Runtime updates must
replace the authenticated manifest and pass every platform build; media commands never
download executable updates outside a reviewed PixShift release.

## Reporting a Vulnerability

Please do not open public issues for security vulnerabilities.

Use private GitHub security advisories:

- [Report a vulnerability](https://github.com/ChangWinde/pixshift/security/advisories/new)

Include:

- affected command(s),
- reproduction steps,
- impact assessment,
- optional mitigation ideas.

## Response Process

- Acknowledge report within 3 business days.
- Triage and validate impact.
- Prepare fix and coordinated disclosure.
