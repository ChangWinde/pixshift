# Advanced Workflow Scripts

These scripts are runnable examples for PixShift advanced commands.

## Scripts

- `compare_quality.sh`: compare two images and print quality metrics.
- `crop_social_pack.sh`: crop a directory to 1:1 with JSON summary.
- `watermark_batch.sh`: apply text watermark to a directory in dry-run mode.
- `montage_board.sh`: create a quick image board.
- `optimize_scan.sh`: run format recommendation scan.
- `watch_once.sh`: run one-shot watch conversion for automation.

## Requirements

- `pixshift` in `PATH`
- [`jq`](https://jqlang.github.io/jq/) for JSON parsing

## Quick Start

```bash
chmod +x ./examples/advanced/*.sh
./examples/advanced/compare_quality.sh a.jpg b.jpg
./examples/advanced/crop_social_pack.sh ./photos ./out
./examples/advanced/watermark_batch.sh ./photos ./out "PixShift"
./examples/advanced/montage_board.sh ./photos ./board.png
./examples/advanced/optimize_scan.sh ./photos
./examples/advanced/watch_once.sh ./incoming ./converted
```

