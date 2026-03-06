# Automation Scripts

These scripts are practical templates built on PixShift's `--json` output mode.

## Scripts

- `dedup_ci.sh`: fail CI when duplicate files are detected.
- `compress_report.sh`: run compression and print byte-level summary.
- `pdf_info_export.sh`: export key PDF metrics.

## Requirements

- `pixshift` in `PATH`
- [`jq`](https://jqlang.github.io/jq/) for JSON parsing

## Quick Start

```bash
chmod +x ./examples/automation/*.sh
./examples/automation/dedup_ci.sh ./assets
./examples/automation/compress_report.sh ./images ./compressed
./examples/automation/pdf_info_export.sh ./report.pdf
```

