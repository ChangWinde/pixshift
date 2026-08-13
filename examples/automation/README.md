# Automation Scripts

These scripts are practical templates built on PixShift's `--json` output mode.

## Scripts

- `plan_apply_loop.sh`: the agent loop end to end — plan with `optimize`,
  preview with `apply --dry-run`, apply, then verify with content hashes.
- `dedup_ci.sh`: fail CI when duplicate files are detected.
- `compress_report.sh`: run compression and print byte-level summary.
- `pdf_info_export.sh`: export key PDF metrics.

## Requirements

- `pixshift` in `PATH`
- [`jq`](https://jqlang.github.io/jq/) for JSON parsing

## Quick Start

```bash
chmod +x ./examples/automation/*.sh
./examples/automation/plan_apply_loop.sh ./photos ./optimized
./examples/automation/dedup_ci.sh ./assets
./examples/automation/compress_report.sh ./images ./compressed
./examples/automation/pdf_info_export.sh ./report.pdf
```

